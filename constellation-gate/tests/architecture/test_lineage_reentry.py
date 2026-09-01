from __future__ import annotations

import pytest
from constellation_node_sdk.transport.packet import create_transport_packet
from constellation_node_sdk.transport.provenance import RoutingProvenance
from support.sdk_worker import SdkWorker

from constellation_gate.routing.dispatch import Dispatcher
from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry


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

    worker = SdkWorker(
        node_name="score",
        action="score",
        handler=lambda org_id, payload: {"status": "completed", "score": 91},
    )

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

    async with worker.client() as client:
        dispatcher = Dispatcher(local_node="gate", registry=registry, client=client)
        await dispatcher.dispatch(ingress_packet)

    assert worker.request_count == 1
    posted_packet = worker.received_packets[0]

    # Ancestry is carried by lineage -- that is what "preserved across reentry"
    # means, and it is unaffected by how hops are scoped.
    assert posted_packet.lineage.parent_id == ingress_packet.header.packet_id
    assert posted_packet.lineage.root_id == ingress_packet.lineage.root_id
    assert posted_packet.lineage.generation == ingress_packet.lineage.generation + 1
    assert posted_packet.provenance.origin_kind == "gate"
    assert posted_packet.provenance.original_source_node == "orchestrator"

    # hop_trace is per-packet observational state, NOT ancestry. A parent hop is
    # bound to the parent's packet_id and transport_hash, so carrying it into the
    # child makes the child fail canonical hop validation at the worker. The child
    # therefore carries exactly its own dispatch hop, bound to its own packet_id.
    assert len(posted_packet.hop_trace) == 1
    dispatch_hop = posted_packet.hop_trace[0]
    assert dispatch_hop.direction == "dispatch"
    assert dispatch_hop.packet_id == posted_packet.header.packet_id
    assert dispatch_hop.target_node == "score"

    # The ingress observation stays where it was observed: on the parent.
    assert all(hop.packet_id == posted_packet.header.packet_id for hop in posted_packet.hop_trace)
