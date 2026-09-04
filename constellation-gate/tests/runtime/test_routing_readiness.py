"""ADR-GATE-014: readiness means routable, not merely 'the process is up'."""

from __future__ import annotations

from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry
from constellation_gate.runtime.routing_readiness import action_routability, routing_readiness


def _registry_with_eie(*, healthy: bool = True) -> NodeRegistry:
    registry = NodeRegistry()
    registry.register_node(
        "eie",
        NodeRegistration(
            node_name="eie",
            internal_url="http://eie:8000",
            supported_actions=("converge", "graph-inference-result"),
            metadata={"owner": "eie"},
            healthy=healthy,
        ),
    )
    return registry


def test_empty_registry_is_not_ready() -> None:
    result = routing_readiness(NodeRegistry())

    assert result["ready"] is False
    assert result["status"] == "not_ready"
    assert result["problems"]


def _registry_with_seam(*, healthy: bool = True) -> NodeRegistry:
    registry = _registry_with_eie(healthy=healthy)
    registry.register_node(
        "eie",
        NodeRegistration(
            node_name="eie",
            internal_url="http://eie:8000",
            supported_actions=("converge", "graph-inference-result", "enrich", "enrich-and-sync"),
            metadata={"owner": "eie"},
            healthy=healthy,
        ),
        overwrite=True,
    )
    registry.register_node(
        "graph",
        NodeRegistration(
            node_name="graph",
            internal_url="http://graph:8000",
            supported_actions=("match", "sync", "outcomes"),
            metadata={"owner": "ceg"},
            healthy=healthy,
        ),
    )
    return registry


def test_default_readiness_requires_the_whole_bidirectional_seam() -> None:
    """EIE alone routes `converge` but not `sync`/`match`/`outcomes` -> not ready."""
    eie_only = routing_readiness(_registry_with_eie())
    assert eie_only["ready"] is False
    missing = {entry["action"] for entry in eie_only["actions"] if not entry["routable"]}
    assert missing == {"enrich", "enrich-and-sync", "match", "sync", "outcomes"}

    both = routing_readiness(_registry_with_seam())
    assert both["ready"] is True
    resolved = {entry["action"]: entry["resolved_node"] for entry in both["actions"]}
    assert resolved["converge"] == "eie"
    assert resolved["enrich"] == "eie"
    assert resolved["sync"] == "graph"
    assert resolved["outcomes"] == "graph"


def test_healthy_eie_makes_converge_routable() -> None:
    result = routing_readiness(_registry_with_eie(), required_actions=("converge",))

    assert result["ready"] is True
    converge = result["actions"][0]
    assert converge["resolved_node"] == "eie"
    assert converge["required_owner"] == "eie"
    assert converge["problem"] is None


def test_unhealthy_eie_is_not_routable() -> None:
    """A registered-but-unhealthy worker must not read as ready."""
    result = routing_readiness(_registry_with_eie(healthy=False), required_actions=("converge",))

    assert result["ready"] is False
    converge = result["actions"][0]
    assert converge["advertising_nodes"] == ["eie"]
    assert converge["healthy_advertising_nodes"] == []
    assert converge["resolved_node"] is None


def test_readiness_reports_the_canonical_owner_for_converge() -> None:
    entry = action_routability(_registry_with_eie(), "converge")
    assert entry["required_owner"] == "eie"
    assert entry["owners"]["eie"] == "eie"


def test_replicas_of_the_same_owner_are_routable() -> None:
    registry = _registry_with_eie()
    registry.register_node(
        "eie-replica-2",
        NodeRegistration(
            node_name="eie-replica-2",
            internal_url="http://eie-2:8000",
            supported_actions=("converge",),
            metadata={"owner": "eie"},
        ),
    )

    result = routing_readiness(registry, required_actions=("converge",))

    assert result["ready"] is True
    assert set(result["actions"][0]["advertising_nodes"]) == {"eie", "eie-replica-2"}


def test_unhealthy_is_distinguished_from_never_registered() -> None:
    """Two different operational problems with two different fixes."""
    unhealthy = action_routability(_registry_with_eie(healthy=False), "converge")
    absent = action_routability(NodeRegistry(), "converge")

    assert unhealthy["advertising_nodes"] == ["eie"]
    assert absent["advertising_nodes"] == []
    assert unhealthy["routable"] is absent["routable"] is False


def test_wrong_owner_claiming_converge_is_not_routable() -> None:
    """Ownership is checked at readiness, not only at registration."""
    registry = NodeRegistry()
    registry.register_node(
        "ceg",
        NodeRegistration(
            node_name="ceg",
            internal_url="http://ceg:8000",
            supported_actions=("match",),
            metadata={"owner": "ceg"},
        ),
    )
    # Force a state registration would have refused, to prove readiness also checks.
    registry._nodes["ceg"] = registry._nodes["ceg"].model_copy(
        update={"supported_actions": ("match", "converge")}
    )

    entry = action_routability(registry, "converge")

    assert entry["routable"] is False
    assert entry["required_owner"] == "eie"
    assert "canonical owner" in (entry["problem"] or "")


def test_unknown_action_requirement_is_reported_not_silently_passed() -> None:
    result = routing_readiness(_registry_with_eie(), required_actions=("never-registered",))

    assert result["ready"] is False
    assert "never-registered" in (result["problems"][0] or "")
