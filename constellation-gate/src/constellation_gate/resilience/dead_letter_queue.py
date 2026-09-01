from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from constellation_node_sdk.transport.packet import TransportPacket


@dataclass(frozen=True)
class DeadLetterEntry:
    packet_id: str
    action: str
    source_node: str
    destination_node: str
    error_type: str
    error_message: str
    failed_at: datetime
    packet: dict[str, Any]


@dataclass
class DeadLetterQueue:
    """
    Process-local, in-memory record of terminally failed packets.

    OBSERVABILITY ONLY. This is NOT a recovery mechanism and must not be
    described as one: entries live in this process's heap, are lost on restart,
    are invisible to every other Gate replica, and are never re-driven. A packet
    reaching this queue has failed and stays failed -- the queue records that it
    happened.

    It keeps a stable quarantine shape that a durable backend can later
    implement. Until then, do not build an operational recovery procedure on it.
    """

    entries: list[DeadLetterEntry] = field(default_factory=list)
    max_entries: int = 1_000

    def put(self, *, packet: TransportPacket, error: Exception) -> DeadLetterEntry:
        entry = DeadLetterEntry(
            packet_id=str(packet.header.packet_id),
            action=packet.header.action,
            source_node=packet.address.source_node,
            destination_node=packet.address.destination_node,
            error_type=error.__class__.__name__,
            error_message=str(error),
            failed_at=datetime.now(UTC),
            packet=packet.model_dump_json_dict(),
        )
        self.entries.append(entry)
        # A sustained outage is precisely when this fills fastest, and each
        # entry holds a full packet dump. Drop oldest rather than grow forever.
        while len(self.entries) > self.max_entries:
            self.entries.pop(0)
        return entry

    def size(self) -> int:
        return len(self.entries)

    def latest(self) -> DeadLetterEntry | None:
        if not self.entries:
            return None
        return self.entries[-1]

    def clear(self) -> None:
        self.entries.clear()
