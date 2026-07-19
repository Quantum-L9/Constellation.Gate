from __future__ import annotations

import pytest
from constellation_node_sdk.transport.packet import create_transport_packet
from constellation_node_sdk.transport.provenance import RoutingProvenance

from constellation_gate.routing.dispatch import Dispatcher
from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry
from constellation_gate.runtime.http_client import AsyncHttpClientManager
from constellation_gate.runtime.node_limits import PerNodeLimiterManager


class CapturingClient:
    def __init__(self) -> None:
        self.calls = 0

    async def post(self, url: str, json: dict, headers: dict, timeout: float):
        self.calls += 1
        from httpx import Request, Response

        response_packet = create_transport_packet(
            action=json["header"]["action"],
            payload={"status": "completed"},
            tenant="tenant-a",
            destination_node="gate",
            source_node="score",
            reply_to="gate",
        )
        return Response(
            status_code=200,
            json=response_packet.model_dump_json_dict(),
            request=Request("POST", url),
        )


@pytest.mark.asyncio
async def test_dispatcher_uses_injected_pooled_client_path() -> None:
    registry = NodeRegistry()
    registry.register_node(
        "score",
        NodeRegistration(
            node_name="score",
            internal_url="http://score:8000",
            supported_actions=("score",),
            max_concurrent=2,
            timeout_ms=15_000,
        ),
    )

    pooled_client = CapturingClient()
    dispatcher = Dispatcher(
        local_node="gate",
        registry=registry,
        client=pooled_client,
        node_limits=PerNodeLimiterManager(),
    )

    packet = create_transport_packet(
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

    result = await dispatcher.dispatch(packet)

    assert result.payload["status"] == "completed"
    assert pooled_client.calls == 1

    manager = AsyncHttpClientManager()
    assert manager.started is False
