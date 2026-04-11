from __future__ import annotations

import pytest

from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry


@pytest.fixture
def sample_registry() -> NodeRegistry:
    registry = NodeRegistry()
    registry.register_node(
        "score",
        NodeRegistration(
            node_name="score",
            internal_url="http://score:8000",
            supported_actions=("score",),
            max_concurrent=10,
            timeout_ms=15_000,
        ),
    )
    registry.register_node(
        "enrich",
        NodeRegistration(
            node_name="enrich",
            internal_url="http://enrich:8000",
            supported_actions=("enrich",),
            max_concurrent=10,
            timeout_ms=30_000,
        ),
    )
    return registry
