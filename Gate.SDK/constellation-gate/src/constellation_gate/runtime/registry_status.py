from __future__ import annotations

from typing import Any

from constellation_gate.routing.node_registry import NodeRegistry


def registry_status(registry: NodeRegistry) -> dict[str, Any]:
    nodes = registry.known_nodes()
    return {
        "node_count": len(nodes),
        "nodes": sorted(nodes),
    }
