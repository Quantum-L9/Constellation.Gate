from __future__ import annotations

from typing import Any

from constellation_node_sdk.transport.packet import TransportPacket

from .logging import packet_log_context


def ingress_event(packet: TransportPacket) -> dict[str, Any]:
    payload = packet_log_context(packet)
    payload["event"] = "gate.ingress"
    return payload


def dispatch_event(packet: TransportPacket, *, target_node: str) -> dict[str, Any]:
    payload = packet_log_context(packet)
    payload.update(
        {
            "event": "gate.dispatch",
            "target_node": target_node.strip().lower(),
        }
    )
    return payload


def workflow_step_event(packet: TransportPacket, *, step_name: str) -> dict[str, Any]:
    payload = packet_log_context(packet)
    payload.update(
        {
            "event": "gate.workflow_step",
            "step_name": step_name.strip().lower(),
        }
    )
    return payload


def failure_event(packet: TransportPacket, *, error: Exception) -> dict[str, Any]:
    payload = packet_log_context(packet)
    payload.update(
        {
            "event": "gate.failure",
            "error_type": error.__class__.__name__,
            "error_message": str(error),
        }
    )
    return payload
