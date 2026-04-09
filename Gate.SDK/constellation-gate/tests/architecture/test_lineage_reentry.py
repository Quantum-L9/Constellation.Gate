from __future__ import annotations

import httpx
import pytest

from constellation_gate.routing.dispatch import Dispatcher
from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry
from constellation_node_sdk.transport.packet import TransportPacket, create_transport_packet
from constellation_node_sdk.transport.provenance import RoutingProvenance


class FakeAsyncClient:
    def __init__(self, response_body: dict) -> None:
        self.response_body = response_body
        self.calls: list[dict] = []

    async def post(self, url: str, json: dict, headers: dict, timeout: float) -> httpx.Response:
        self.calls.append(
            {
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": timeout,
            }
        )
        request = httpx.Request("POST", url)
        return httpx.Response(status_code=200, json=self.response_body, request=request)


@pytest.mark.asyncio
async def test_lineage_is_preserved_across_gate_reentry_and_dispatch() -> None:
    registry = NodeRegistry()
    registry.register_node(
        "score",
        NodeRegistration(
            node_name="score",
            internal_url="http://score:8000",
            supported_actions=("score",),
            timeout_ms=15_000,
        ),
    )

    worker_response = create_transport_packet(
        action="score",
        payload={"status": "completed", "score": 91},
        tenant="tenant-a",
        destination_node="gate",
        source_node="score",
        reply_to="gate",
    )
    fake_client = FakeAsyncClient(worker_response.model_dump_json_dict())
    dispatcher = Dispatcher(local_node="gate", registry=registry, client=fake_client)

    ingress_packet = create_transport_packet(
        action="score",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="orchestrator",
        reply_to="orchestrator",
        provenance=RoutingProvenance(
            origin_kind="node",
            requested_action="score",
            resolved_by_gate=False,
            original_source_node="orchestrator",
        ),
    )

    await dispatcher.dispatch(ingress_packet)

    assert len(fake_client.calls) == 1
    posted_packet = TransportPacket.model_validate(fake_client.calls[0]["json"])

    assert posted_packet.lineage.parent_id == ingress_packet.header.packet_id
    assert posted_packet.lineage.root_id == ingress_packet.lineage.root_id
    assert posted_packet.lineage.generation == ingress_packet.lineage.generation + 1
    assert posted_packet.provenance.origin_kind == "gate"
    assert posted_packet.provenance.original_source_node == "orchestrator"
    assert len(posted_packet.hop_trace) == 2
    assert posted_packet.hop_trace[0].direction == "ingress"
    assert posted_packet.hop_trace[1].direction == "dispatch"
