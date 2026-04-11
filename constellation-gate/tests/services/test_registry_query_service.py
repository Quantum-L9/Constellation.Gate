from __future__ import annotations

from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry
from constellation_gate.services.registry_query_service import RegistryQueryService


def test_registry_query_service_returns_sorted_json_safe_snapshot() -> None:
    registry = NodeRegistry()
    registry.register_node(
        "score",
        NodeRegistration(
            node_name="score",
            internal_url="http://score:8000",
            supported_actions=("score",),
            priority_class="P1",
            max_concurrent=25,
        ),
    )
    registry.register_node(
        "enrich",
        NodeRegistration(
            node_name="enrich",
            internal_url="http://enrich:8000",
            supported_actions=("enrich",),
            priority_class="P2",
            max_concurrent=10,
        ),
    )

    service = RegistryQueryService(registry)
    snapshot = service.snapshot()

    assert list(snapshot.keys()) == ["enrich", "score"]
    assert snapshot["enrich"]["node_name"] == "enrich"
    assert snapshot["score"]["internal_url"] == "http://score:8000"
    assert snapshot["score"]["supported_actions"] == ["score"]


def test_registry_query_service_reports_known_nodes_and_count() -> None:
    registry = NodeRegistry()
    registry.register_node(
        "score",
        NodeRegistration(
            node_name="score",
            internal_url="http://score:8000",
            supported_actions=("score",),
        ),
    )

    service = RegistryQueryService(registry)

    assert service.known_nodes() == ["score"]
    assert service.node_count() == 1
