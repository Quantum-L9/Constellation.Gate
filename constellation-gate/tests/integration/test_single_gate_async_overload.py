from __future__ import annotations

import pytest
from constellation_node_sdk.transport.packet import create_transport_packet
from constellation_node_sdk.transport.provenance import RoutingProvenance

from constellation_gate.routing.dispatch import Dispatcher
from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry
from constellation_gate.runtime.node_limits import (
    NodeLimitExceededError,
    PerNodeLimiterManager,
)


class FastClient:
    async def post(self, url: str, json: dict, headers: dict, timeout: float):
        del url, headers, timeout
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
            request=Request("POST", "http://score:8000/v1/execute"),
        )


@pytest.mark.asyncio
async def test_single_gate_async_overload_rejects_when_node_limit_is_saturated() -> None:
    registry = NodeRegistry()
    registry.register_node(
        "score",
        NodeRegistration(
            node_name="score",
            internal_url="http://score:8000",
            supported_actions=("score",),
            max_concurrent=1,
            timeout_ms=15_000,
        ),
    )
    node_limits = PerNodeLimiterManager()
    node_limits.ensure_node_limit("score", 1)
    await node_limits.acquire("score")

    dispatcher = Dispatcher(
        local_node="gate",
        registry=registry,
        client=FastClient(),
        node_limits=node_limits,
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

    with pytest.raises(NodeLimitExceededError):
        await dispatcher.dispatch(packet)

    node_limits.release("score")
