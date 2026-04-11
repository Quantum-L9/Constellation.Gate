from __future__ import annotations

from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry


def test_registry_resolves_least_loaded_healthy_node_for_action() -> None:
    registry = NodeRegistry()
    registry.register_node(
        "enrich-a",
        NodeRegistration(
            node_name="enrich-a",
            internal_url="http://enrich-a:8000",
            supported_actions=("enrich",),
            active_requests=3,
        ),
    )
    registry.register_node(
        "enrich-b",
        NodeRegistration(
            node_name="enrich-b",
            internal_url="http://enrich-b:8000",
            supported_actions=("enrich",),
            active_requests=1,
        ),
    )

    resolved = registry.resolve_action("enrich")
    assert resolved.node_name == "enrich-b"


def test_registry_resolve_destination_rejects_unhealthy_node() -> None:
    registry = NodeRegistry()
    registry.register_node(
        "score",
        NodeRegistration(
            node_name="score",
            internal_url="http://score:8000",
            supported_actions=("score",),
            healthy=False,
        ),
    )

    try:
        registry.resolve_destination("score")
    except LookupError as exc:
        assert "unhealthy" in str(exc)
    else:
        raise AssertionError("expected LookupError")


def test_registry_increment_and_decrement_active_track_concurrency() -> None:
    registry = NodeRegistry()
    registry.register_node(
        "score",
        NodeRegistration(
            node_name="score",
            internal_url="http://score:8000",
            supported_actions=("score",),
            max_concurrent=2,
            active_requests=0,
        ),
    )

    registry.increment_active("score")
    registry.increment_active("score")
    snapshot = registry.snapshot()
    assert snapshot["score"].active_requests == 2

    registry.decrement_active("score")
    snapshot = registry.snapshot()
    assert snapshot["score"].active_requests == 1
