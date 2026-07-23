from __future__ import annotations

from constellation_node_sdk.transport.packet import create_transport_packet

from constellation_gate.boundary.delegation_factory import DelegationFactory


def test_orchestrator_follow_up_work_targets_gate_not_peer() -> None:
    parent = create_transport_packet(
        action="full_pipeline",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="orchestrator",
        source_node="gate",
        reply_to="gate",
    )

    packet = DelegationFactory().build(
        parent=parent,
        local_node="orchestrator",
        action="score",
        payload={"entity_id": "42", "industry": "fintech"},
    )

    assert packet.address.source_node == "orchestrator"
    assert packet.address.destination_node == "gate"
    assert packet.address.reply_to == "orchestrator"
    assert packet.provenance.origin_kind == "node"
    assert packet.provenance.resolved_by_gate is False
    assert packet.lineage.parent_id == parent.header.packet_id
