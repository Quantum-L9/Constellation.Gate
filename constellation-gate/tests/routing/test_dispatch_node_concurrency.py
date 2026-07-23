from __future__ import annotations

import asyncio

import httpx
import pytest
from constellation_node_sdk.transport.packet import create_transport_packet
from constellation_node_sdk.transport.provenance import RoutingProvenance

from constellation_gate.routing.dispatch import Dispatcher
from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry
from constellation_gate.runtime.node_limits import NodeLimitExceededError, PerNodeLimiterManager


class BlockingClient:
    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def post(self, url: str, json: dict, headers: dict, timeout: float) -> httpx.Response:
        del url, headers, timeout
        self.entered.set()
        await self.release.wait()
        request = httpx.Request("POST", "http://score:8000/v1/execute")
        response_packet = create_transport_packet(
            action="score",
            payload={"status": "completed"},
            tenant="tenant-a",
            destination_node="gate",
            source_node="score",
            reply_to="gate",
        )
        return httpx.Response(
            status_code=200,
            json=response_packet.model_dump_json_dict(),
            request=request,
        )


@pytest.mark.asyncio
async def test_dispatch_enforces_per_node_concurrency_limit() -> None:
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
    client = BlockingClient()
    dispatcher = Dispatcher(
        local_node="gate",
        registry=registry,
        client=client,
        node_limits=node_limits,
    )

    packet_a = create_transport_packet(
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
    packet_b = create_transport_packet(
        action="score",
        payload={"entity_id": "43"},
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

    first_task = asyncio.create_task(dispatcher.dispatch(packet_a))
    await client.entered.wait()

    with pytest.raises(NodeLimitExceededError):
        await dispatcher.dispatch(packet_b)

    client.release.set()
    result = await first_task
    assert result.payload["status"] == "completed"
