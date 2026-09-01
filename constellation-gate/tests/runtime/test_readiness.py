"""Readiness answers 'can Gate route this action right now?'."""

from __future__ import annotations

from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry
from constellation_gate.runtime.readiness import check_action_routable, readiness_report


def _eie_registration(*, healthy: bool = True) -> NodeRegistration:
    """The exact shape EIE registers (see EIE app/services/gate_registration.py)."""
    return NodeRegistration(
        node_name="enrichment-engine",
        internal_url="http://enrichment-engine:8000",
        supported_actions=("converge", "graph-inference-result", "enrich", "enrich-and-sync"),
        health_endpoint="/api/v1/health",
        metadata={"owner": "eie", "version": "2.3.0", "type": "enrichment"},
        healthy=healthy,
    )


def test_unregistered_action_is_not_routable() -> None:
    result = check_action_routable(NodeRegistry(), "converge")
    assert result.routable is False
    assert result.required_owner == "eie"
    assert result.resolved_node is None
    assert result.reasons


def test_converge_is_routable_when_eie_is_registered_and_healthy() -> None:
    registry = NodeRegistry()
    registry.register_node("enrichment-engine", _eie_registration())

    result = check_action_routable(registry, "converge")
    assert result.routable is True
    assert result.resolved_node == "enrichment-engine"
    assert result.resolved_owner == "eie"
    assert result.required_owner == "eie"
    assert result.reasons == ()


def test_unhealthy_owner_is_not_routable() -> None:
    registry = NodeRegistry()
    registry.register_node("enrichment-engine", _eie_registration(healthy=False))

    result = check_action_routable(registry, "converge")
    assert result.routable is False


def test_report_is_ready_only_when_every_required_action_routes() -> None:
    registry = NodeRegistry()
    registry.register_node("enrichment-engine", _eie_registration())

    assert readiness_report(registry, required_actions=("converge",))["ready"] is True
    not_ready = readiness_report(registry, required_actions=("converge", "match"))
    assert not_ready["ready"] is False
    assert "enrichment-engine" in not_ready["registered_nodes"]


def test_no_declared_requirement_is_ready() -> None:
    assert readiness_report(NodeRegistry())["ready"] is True
