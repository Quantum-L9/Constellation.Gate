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
    In-memory dead letter queue for failed packets.

    This is intentionally simple and process-local. It preserves a stable
    quarantine contract that can later be externalized to durable storage.
    """

    entries: list[DeadLetterEntry] = field(default_factory=list)

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
        return entry

    def size(self) -> int:
        return len(self.entries)

    def latest(self) -> DeadLetterEntry | None:
        if not self.entries:
            return None
        return self.entries[-1]

    def clear(self) -> None:
        self.entries.clear()
