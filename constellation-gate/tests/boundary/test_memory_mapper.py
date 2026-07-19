from __future__ import annotations

from constellation_node_sdk.transport.packet import create_transport_packet

from constellation_gate.boundary.memory_mapper import MemoryMapper


def test_memory_mapper_to_record_projects_transport_packet_fields() -> None:
    packet = create_transport_packet(
        action="score",
        payload={"entity_id": "42", "score": 91},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )

    record = MemoryMapper().to_record(packet)

    assert record["packet_id"] == str(packet.header.packet_id)
    assert record["packet_type"] == packet.header.packet_type
    assert record["action"] == "score"
    assert record["source_node"] == "client"
    assert record["destination_node"] == "gate"
    assert record["tenant_org_id"] == "tenant-a"
    assert record["root_id"] == str(packet.lineage.root_id)
    assert record["parent_id"] is None
    assert record["generation"] == 0
    assert record["payload"]["score"] == 91
    assert record["transport_hash"] == packet.security.transport_hash
    assert record["hop_count"] == 0
    assert isinstance(record["created_at"], str)


def test_memory_mapper_failure_record_adds_failure_metadata() -> None:
    packet = create_transport_packet(
        action="enrich",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="orchestrator",
        reply_to="orchestrator",
    )

    record = MemoryMapper().failure_record(packet, RuntimeError("boom"))

    assert record["failure"] is True
    assert record["error_type"] == "RuntimeError"
    assert record["error_message"] == "boom"
    assert record["action"] == "enrich"
    assert record["source_node"] == "orchestrator"
