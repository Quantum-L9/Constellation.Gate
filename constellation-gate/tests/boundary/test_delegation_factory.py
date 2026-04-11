from __future__ import annotations

from constellation_gate.boundary.delegation_factory import DelegationFactory
from constellation_node_sdk.transport.packet import create_transport_packet


def test_delegation_factory_builds_gate_reentry_packet_for_follow_up_work() -> None:
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
        idempotency_key="delegated-score-1",
        timeout_ms=20_000,
    )

    assert packet.header.action == "score"
    assert packet.header.idempotency_key == "delegated-score-1"
    assert packet.header.timeout_ms == 20_000
    assert packet.address.source_node == "orchestrator"
    assert packet.address.destination_node == "gate"
    assert packet.address.reply_to == "orchestrator"
    assert packet.lineage.parent_id == parent.header.packet_id
    assert packet.lineage.root_id == parent.lineage.root_id
    assert packet.lineage.generation == parent.lineage.generation + 1
    assert packet.provenance.origin_kind == "node"
    assert packet.provenance.requested_action == "score"
    assert packet.provenance.resolved_by_gate is False
    assert packet.provenance.original_source_node == "orchestrator"
    assert packet.payload["industry"] == "fintech"


def test_delegation_factory_inherits_parent_timeout_when_override_missing() -> None:
    parent = create_transport_packet(
        action="full_pipeline",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="orchestrator",
        source_node="gate",
        reply_to="gate",
        timeout_ms=45_000,
    )

    packet = DelegationFactory().build(
        parent=parent,
        local_node="orchestrator",
        action="enrich",
        payload={"entity_id": "42"},
    )

    assert packet.header.timeout_ms == 45_000
    assert packet.address.destination_node == "gate"
