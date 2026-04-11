from __future__ import annotations

from constellation_gate.boundary.replay_factory import ReplayFactory
from constellation_node_sdk.transport.packet import create_transport_packet


def test_replay_factory_builds_gate_reentry_packet_in_replay_mode() -> None:
    original = create_transport_packet(
        action="score",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="orchestrator",
        reply_to="orchestrator",
        idempotency_key="score-42",
        timeout_ms=15_000,
    )

    packet = ReplayFactory().build(
        original=original,
        source_node="orchestrator",
    )

    assert packet.header.packet_id != original.header.packet_id
    assert packet.header.action == original.header.action
    assert packet.header.packet_type == original.header.packet_type
    assert packet.header.replay_mode is True
    assert packet.header.idempotency_key == "score-42"
    assert packet.address.source_node == "orchestrator"
    assert packet.address.destination_node == "gate"
    assert packet.address.reply_to == "orchestrator"
    assert packet.lineage.parent_id == original.header.packet_id
    assert packet.lineage.root_id == original.lineage.root_id
    assert packet.lineage.generation == original.lineage.generation + 1
    assert packet.provenance.origin_kind == "node"
    assert packet.provenance.resolved_by_gate is False
    assert packet.provenance.original_source_node == "orchestrator"
    assert packet.payload == original.payload


def test_replay_factory_client_source_produces_client_origin_reentry() -> None:
    original = create_transport_packet(
        action="query",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )

    packet = ReplayFactory().build(
        original=original,
        source_node="client",
    )

    assert packet.header.replay_mode is True
    assert packet.address.source_node == "client"
    assert packet.address.destination_node == "gate"
    assert packet.provenance.origin_kind == "client"
    assert packet.provenance.original_source_node is None
