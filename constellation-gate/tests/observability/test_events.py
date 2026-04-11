from __future__ import annotations

from constellation_gate.observability.events import (
    dispatch_event,
    failure_event,
    ingress_event,
    workflow_step_event,
)
from constellation_node_sdk.transport.packet import create_transport_packet


def test_ingress_event_contains_event_name() -> None:
    packet = create_transport_packet(
        action="score",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )

    event = ingress_event(packet)

    assert event["event"] == "gate.ingress"
    assert event["action"] == "score"


def test_dispatch_event_contains_target_node() -> None:
    packet = create_transport_packet(
        action="score",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="orchestrator",
        reply_to="orchestrator",
    )

    event = dispatch_event(packet, target_node="score")

    assert event["event"] == "gate.dispatch"
    assert event["target_node"] == "score"


def test_workflow_step_and_failure_events() -> None:
    packet = create_transport_packet(
        action="full_pipeline",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )

    step = workflow_step_event(packet, step_name="enrich")
    failure = failure_event(packet, error=RuntimeError("boom"))

    assert step["event"] == "gate.workflow_step"
    assert step["step_name"] == "enrich"
    assert failure["event"] == "gate.failure"
    assert failure["error_type"] == "RuntimeError"
