from __future__ import annotations

import httpx

from constellation_gate.routing.dispatch import Dispatcher
from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry
from constellation_node_sdk.transport.packet import TransportPacket, create_transport_packet
from constellation_node_sdk.transport.provenance import RoutingProvenance


class FakeAsyncClient:
    def __init__(self, response_body: dict) -> None:
        self._response_body = response_body
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
        return httpx.Response(status_code=200, json=self._response_body, request=request)


def test_dispatch_creates_gate_authored_worker_dispatch_and_posts_to_worker() -> None:
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

    response_packet = create_transport_packet(
        action="score",
        payload={"status": "completed", "score": 91},
        tenant="tenant-a",
        destination_node="gate",
        source_node="score",
        reply_to="gate",
    )
    fake_client = FakeAsyncClient(response_packet.model_dump_json_dict())
    dispatcher = Dispatcher(local_node="gate", registry=registry, client=fake_client)

    inbound_packet = create_transport_packet(
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

    result = __import__("asyncio").run(dispatcher.dispatch(inbound_packet))

    assert isinstance(result, TransportPacket)
    assert result.payload["score"] == 91
    assert len(fake_client.calls) == 1
    call = fake_client.calls[0]
    assert call["url"] == "http://score:8000/v1/execute"

    posted_packet = TransportPacket.model_validate(call["json"])
    assert posted_packet.address.source_node == "gate"
    assert posted_packet.address.destination_node == "score"
    assert posted_packet.provenance.origin_kind == "gate"
    assert posted_packet.provenance.resolved_by_gate is True
