"""The shipped static registry must load through the real loader.

Before this file existed the YAML was a list under a `nodes:` key while the
loader expects a mapping of node_name -> registration, so
GATE_NODE_REGISTRY_PATH pointing at the repository's own file failed at
startup with "node registry YAML must be a mapping".
"""

from __future__ import annotations

from pathlib import Path

from constellation_gate.routing.node_registry import NodeRegistry

SHIPPED = Path(__file__).resolve().parents[2] / "src/constellation_gate/config/node_registry.yaml"


def test_shipped_registry_loads_and_owns_converge() -> None:
    registry = NodeRegistry()
    registry.load_from_yaml(str(SHIPPED))

    snapshot = registry.snapshot()
    assert "enrichment-engine" in snapshot
    eie = snapshot["enrichment-engine"]
    assert "converge" in eie.supported_actions
    assert eie.metadata["owner"] == "eie"
    assert eie.health_endpoint == "/api/v1/health"
    assert eie.timeout_ms == 25_000


def test_shipped_registry_routes_converge_to_the_enrichment_worker() -> None:
    registry = NodeRegistry()
    registry.load_from_yaml(str(SHIPPED))
    assert registry.resolve_action("converge").node_name == "enrichment-engine"
