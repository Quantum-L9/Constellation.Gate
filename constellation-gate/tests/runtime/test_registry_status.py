from __future__ import annotations

from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry
from constellation_gate.runtime.registry_status import registry_status


def test_registry_status_lists_nodes() -> None:
    registry = NodeRegistry()
    registry.register_node(
        "score",
        NodeRegistration(
            node_name="score",
            internal_url="http://score",
            supported_actions=("score",),
        ),
    )

    status = registry_status(registry)

    assert status["node_count"] == 1
    assert status["nodes"] == ["score"]
