```yaml
# filename: examples/registry/node_registry.yaml
nodes:
  orchestrator:
    internal_url: http://orchestrator:8000
    supported_actions:
      - full_pipeline
      - orchestrate
    priority_class: P1
    max_concurrent: 10
    health_endpoint: /v1/health
    timeout_ms: 60000
    metadata:
      role: orchestrator
      domain: control_plane
      version: "1.0.0"
      owner: platform

  enrich:
    internal_url: http://enrich:8000
    supported_actions:
      - enrich
      - entity.enrich
    priority_class: P2
    max_concurrent: 20
    health_endpoint: /v1/health
    timeout_ms: 30000
    metadata:
      role: worker
      domain: research
      version: "1.0.0"
      owner: enrichment

  score:
    internal_url: http://score:8000
    supported_actions:
      - score
      - entity.score
    priority_class: P1
    max_concurrent: 25
    health_endpoint: /v1/health
    timeout_ms: 15000
    metadata:
      role: worker
      domain: matching
      version: "1.0.0"
      owner: scoring

  memory:
    internal_url: http://memory:8000
    supported_actions:
      - memory.write
      - memory.read
    priority_class: P2
    max_concurrent: 15
    health_endpoint: /v1/health
    timeout_ms: 20000
    metadata:
      role: worker
      domain: memory
      version: "1.0.0"
      owner: platform

defaults:
  health_check_interval_seconds: 15
  mark_unhealthy_after_failures: 3
  registration_source: example
```

```yaml
# filename: examples/workflows/full_pipeline.yaml
workflows:
  full_pipeline:
    description: "Canonical enrich -> score pipeline executed entirely through Gate"
    steps:
      - action: enrich
        timeout_ms: 30000
        payload_transform: merge_payload
        condition: null
        target_node: null

      - action: score
        timeout_ms: 15000
        payload_transform: merge_results
        condition: null
        target_node: null
```

```python
# filename: src/constellation_gate/observability/audit_logger.py
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from constellation_node_sdk.transport.packet import TransportPacket

logger = logging.getLogger("constellation_gate.audit")


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _json_default(value: Any) -> str:
    return str(value)


@dataclass(frozen=True)
class AuditEvent:
    event_type: str
    packet_id: str
    action: str
    source_node: str
    destination_node: str
    tenant_org_id: str
    root_id: str
    parent_id: str | None
    generation: int
    timestamp: str
    details: dict[str, Any]

    def to_log_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "packet_id": self.packet_id,
            "action": self.action,
            "source_node": self.source_node,
            "destination_node": self.destination_node,
            "tenant_org_id": self.tenant_org_id,
            "root_id": self.root_id,
            "parent_id": self.parent_id,
            "generation": self.generation,
            "timestamp": self.timestamp,
            "details": self.details,
        }


def build_audit_event(
    *,
    event_type: str,
    packet: TransportPacket,
    details: dict[str, Any] | None = None,
    timestamp: str | None = None,
) -> AuditEvent:
    return AuditEvent(
        event_type=event_type.strip().lower(),
        packet_id=str(packet.header.packet_id),
        action=packet.header.action,
        source_node=packet.address.source_node,
        destination_node=packet.address.destination_node,
        tenant_org_id=packet.tenant.org_id,
        root_id=str(packet.lineage.root_id),
        parent_id=None if packet.lineage.parent_id is None else str(packet.lineage.parent_id),
        generation=packet.lineage.generation,
        timestamp=timestamp or _utc_now_iso(),
        details={} if details is None else dict(details),
    )


class AuditLogger:
    """
    Structured Gate audit logger.

    Purpose:
    - emit stable, machine-parsable audit records
    - preserve core execution facts without redefining TransportPacket
    - provide one place to standardize security / routing / execution audit events

    This logger is intentionally append-only in spirit: it emits facts about
    what Gate observed or decided, keyed by packet lineage identifiers.
    """

    def __init__(self, *, base_logger: logging.Logger | None = None) -> None:
        self._logger = base_logger or logger

    def emit(
        self,
        *,
        event_type: str,
        packet: TransportPacket,
        details: dict[str, Any] | None = None,
        level: int = logging.INFO,
    ) -> AuditEvent:
        event = build_audit_event(
            event_type=event_type,
            packet=packet,
            details=details,
        )
        self._logger.log(
            level,
            self._serialize(event),
            extra={"audit_event": event.to_log_dict()},
        )
        return event

    def ingress_validated(self, *, packet: TransportPacket, request_id: str | None = None) -> AuditEvent:
        return self.emit(
            event_type="ingress_validated",
            packet=packet,
            details={
                "request_id": request_id,
                "packet_type": packet.header.packet_type,
                "replay_mode": packet.header.replay_mode,
                "idempotency_key": packet.header.idempotency_key,
                "hop_count": len(packet.hop_trace),
            },
        )

    def routing_resolved(
        self,
        *,
        packet: TransportPacket,
        resolved_node: str,
        policy: str = "action_resolution",
    ) -> AuditEvent:
        return self.emit(
            event_type="routing_resolved",
            packet=packet,
            details={
                "resolved_node": resolved_node,
                "policy": policy,
            },
        )

    def dispatch_issued(
        self,
        *,
        packet: TransportPacket,
        target_node: str,
        timeout_ms: int,
    ) -> AuditEvent:
        return self.emit(
            event_type="dispatch_issued",
            packet=packet,
            details={
                "target_node": target_node,
                "timeout_ms": timeout_ms,
                "origin_kind": packet.provenance.origin_kind,
                "resolved_by_gate": packet.provenance.resolved_by_gate,
            },
        )

    def workflow_step_started(
        self,
        *,
        packet: TransportPacket,
        workflow_name: str,
        step_action: str,
        step_index: int,
    ) -> AuditEvent:
        return self.emit(
            event_type="workflow_step_started",
            packet=packet,
            details={
                "workflow_name": workflow_name,
                "step_action": step_action,
                "step_index": step_index,
            },
        )

    def workflow_step_completed(
        self,
        *,
        packet: TransportPacket,
        workflow_name: str,
        step_action: str,
        step_index: int,
        duration_ms: int,
    ) -> AuditEvent:
        return self.emit(
            event_type="workflow_step_completed",
            packet=packet,
            details={
                "workflow_name": workflow_name,
                "step_action": step_action,
                "step_index": step_index,
                "duration_ms": duration_ms,
            },
        )

    def execution_completed(
        self,
        *,
        packet: TransportPacket,
        status: str,
        duration_ms: int,
    ) -> AuditEvent:
        return self.emit(
            event_type="execution_completed",
            packet=packet,
            details={
                "status": status,
                "duration_ms": duration_ms,
            },
        )

    def execution_failed(
        self,
        *,
        packet: TransportPacket,
        error: Exception,
        duration_ms: int | None = None,
        dead_lettered: bool = False,
    ) -> AuditEvent:
        return self.emit(
            event_type="execution_failed",
            packet=packet,
            details={
                "error_type": error.__class__.__name__,
                "error_message": str(error),
                "duration_ms": duration_ms,
                "dead_lettered": dead_lettered,
            },
            level=logging.ERROR,
        )

    def admission_rejected(
        self,
        *,
        packet: TransportPacket,
        reason: str,
    ) -> AuditEvent:
        return self.emit(
            event_type="admission_rejected",
            packet=packet,
            details={"reason": reason},
            level=logging.WARNING,
        )

    def admin_registry_mutation(
        self,
        *,
        packet: TransportPacket,
        registered_nodes: list[str],
        overwrite: bool,
    ) -> AuditEvent:
        return self.emit(
            event_type="admin_registry_mutation",
            packet=packet,
            details={
                "registered_nodes": registered_nodes,
                "overwrite": overwrite,
            },
        )

    def _serialize(self, event: AuditEvent) -> str:
        return json.dumps(
            event.to_log_dict(),
            sort_keys=True,
            separators=(",", ":"),
            default=_json_default,
        )
```
