from __future__ import annotations

from constellation_gate.observability.tracing import dispatch_trace, packet_trace
from constellation_node_sdk.transport.packet import create_transport_packet


def test_packet_trace_contains_lineage_fields() -> None:
    packet = create_transport_packet(
        action="enrich",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )

    trace = packet_trace(packet)

    assert trace["packet_id"] == str(packet.header.packet_id)
    assert trace["root_id"] == str(packet.lineage.root_id)
    assert trace["generation"] == 0
    assert "timestamp" in trace


def test_dispatch_trace_adds_target_node() -> None:
    packet = create_transport_packet(
        action="score",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="orchestrator",
        reply_to="orchestrator",
    )

    trace = dispatch_trace(packet, target_node="score")

    assert trace["target_node"] == "score"
    assert trace["requested_action"] == packet.provenance.requested_action
