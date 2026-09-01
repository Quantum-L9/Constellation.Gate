from __future__ import annotations

import asyncio

from constellation_node_sdk.transport.packet import TransportPacket, create_transport_packet
from constellation_node_sdk.transport.provenance import RoutingProvenance
from support.sdk_worker import SdkWorker

from constellation_gate.routing.dispatch import Dispatcher
from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry


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

    worker = SdkWorker(
        node_name="score",
        action="score",
        handler=lambda org_id, payload: {"status": "completed", "score": 91},
    )

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

    async def run() -> TransportPacket:
        async with worker.client() as client:
            dispatcher = Dispatcher(local_node="gate", registry=registry, client=client)
            return await dispatcher.dispatch(inbound_packet)

    result = asyncio.run(run())

    assert isinstance(result, TransportPacket)
    assert result.payload["score"] == 91
    assert worker.request_count == 1
    # The SDK owns the endpoint: Gate supplies a base URL from its registry and
    # the canonical /v1/execute path is appended for it.
    assert str(worker.requests[0].url) == "http://score:8000/v1/execute"

    posted_packet = worker.received_packets[0]
    assert posted_packet.address.source_node == "gate"
    assert posted_packet.address.destination_node == "score"
    assert posted_packet.provenance.origin_kind == "gate"
    assert posted_packet.provenance.resolved_by_gate is True
