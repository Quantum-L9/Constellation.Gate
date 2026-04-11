from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from constellation_node_sdk.transport.packet import TransportPacket


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def packet_trace(packet: TransportPacket) -> dict[str, Any]:
    return {
        "trace_id": packet.header.trace_id,
        "correlation_id": packet.header.correlation_id,
        "packet_id": str(packet.header.packet_id),
        "root_id": str(packet.lineage.root_id),
        "parent_id": None if packet.lineage.parent_id is None else str(packet.lineage.parent_id),
        "generation": packet.lineage.generation,
        "hop_count": len(packet.hop_trace),
        "timestamp": utc_now_iso(),
    }


def dispatch_trace(packet: TransportPacket, *, target_node: str) -> dict[str, Any]:
    trace = packet_trace(packet)
    trace.update(
        {
            "target_node": target_node.strip().lower(),
            "requested_action": packet.provenance.requested_action,
            "resolved_by_gate": packet.provenance.resolved_by_gate,
        }
    )
    return trace
