from __future__ import annotations

import json
import logging
import sys
from typing import Any

from constellation_node_sdk.transport.packet import TransportPacket


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "event"):
            payload["event"] = record.event
        if hasattr(record, "context") and isinstance(record.context, dict):
            payload.update(record.context)
        return json.dumps(payload, sort_keys=True)


def configure_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter())
    root.addHandler(handler)


def packet_log_context(packet: TransportPacket) -> dict[str, Any]:
    return {
        "packet_id": str(packet.header.packet_id),
        "root_id": str(packet.lineage.root_id),
        "action": packet.header.action,
        "source_node": packet.address.source_node,
        "destination_node": packet.address.destination_node,
        "origin_kind": packet.provenance.origin_kind,
        "hop_count": len(packet.hop_trace),
        "generation": packet.lineage.generation,
    }


def log_packet_event(logger: logging.Logger, *, event: str, packet: TransportPacket, **extra: Any) -> None:
    context = packet_log_context(packet)
    context.update(extra)
    logger.info(
        event,
        extra={
            "event": event,
            "context": context,
        },
    )
