from __future__ import annotations

from constellation_node_sdk.transport.packet import create_transport_packet

from constellation_gate.resilience.dead_letter_queue import DeadLetterQueue


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


def test_dead_letter_queue_is_bounded() -> None:
    """A sustained outage must not turn the DLQ into a memory leak."""
    from constellation_node_sdk.transport.packet import create_transport_packet

    from constellation_gate.resilience.dead_letter_queue import DeadLetterQueue

    queue = DeadLetterQueue(max_entries=10)
    for i in range(50):
        packet = create_transport_packet(
            action="score",
            payload={"n": i},
            tenant="tenant-a",
            destination_node="gate",
            source_node="client",
            reply_to="client",
        )
        queue.put(packet=packet, error=RuntimeError(f"failure {i}"))

    assert queue.size() == 10
    latest = queue.latest()
    assert latest is not None
    assert latest.error_message == "failure 49"
