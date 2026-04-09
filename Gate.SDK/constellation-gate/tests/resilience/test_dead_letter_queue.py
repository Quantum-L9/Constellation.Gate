from __future__ import annotations

from constellation_gate.resilience.dead_letter_queue import DeadLetterQueue
from constellation_node_sdk.transport.packet import create_transport_packet


def test_dead_letter_queue_captures_failed_packet() -> None:
    dlq = DeadLetterQueue()
    packet = create_transport_packet(
        action="score",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )

    entry = dlq.put(packet=packet, error=RuntimeError("boom"))

    assert dlq.size() == 1
    assert entry.packet_id == str(packet.header.packet_id)
    assert entry.action == "score"
    assert entry.error_type == "RuntimeError"
    assert entry.error_message == "boom"
    assert entry.packet["header"]["action"] == "score"


def test_dead_letter_queue_latest_and_clear() -> None:
    dlq = DeadLetterQueue()
    packet = create_transport_packet(
        action="enrich",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )

    dlq.put(packet=packet, error=ValueError("bad"))
    latest = dlq.latest()

    assert latest is not None
    assert latest.error_type == "ValueError"

    dlq.clear()
    assert dlq.size() == 0
    assert dlq.latest() is None
