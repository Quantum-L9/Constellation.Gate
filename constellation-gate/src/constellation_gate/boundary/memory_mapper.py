from __future__ import annotations

from typing import Any

from constellation_node_sdk.transport.packet import TransportPacket


class MemoryMapper:
    """
    Maps transport packets to persistence-safe memory records.

    Gate uses this adapter when deriving storage/audit projections from the
    transport packet without redefining the transport contract itself.
    """

    def to_record(self, packet: TransportPacket) -> dict[str, Any]:
        return {
            "packet_id": str(packet.header.packet_id),
            "packet_type": packet.header.packet_type,
            "action": packet.header.action,
            "source_node": packet.address.source_node,
            "destination_node": packet.address.destination_node,
            "tenant_org_id": packet.tenant.org_id,
            "root_id": str(packet.lineage.root_id),
            "parent_id": (
                None if packet.lineage.parent_id is None else str(packet.lineage.parent_id)
            ),
            "generation": packet.lineage.generation,
            "payload": packet.payload,
            "transport_hash": packet.security.transport_hash,
            "hop_count": len(packet.hop_trace),
            "created_at": packet.header.created_at.isoformat(),
        }

    def failure_record(self, packet: TransportPacket, error: Exception) -> dict[str, Any]:
        record = self.to_record(packet)
        record.update(
            {
                "failure": True,
                "error_type": error.__class__.__name__,
                "error_message": str(error),
            }
        )
        return record
