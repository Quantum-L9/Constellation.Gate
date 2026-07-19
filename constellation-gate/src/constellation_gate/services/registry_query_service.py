from __future__ import annotations

from typing import Any

from constellation_gate.routing.node_registry import NodeRegistry


class RegistryQueryService:
    """
    Read-only registry inspection service for admin and status endpoints.
    """

    def __init__(self, registry: NodeRegistry) -> None:
        self._registry = registry

    def snapshot(self) -> dict[str, dict[str, Any]]:
        registrations = self._registry.snapshot()
        return {
            node_name: registration.model_dump(mode="json")
            for node_name, registration in sorted(registrations.items())
        }

    def known_nodes(self) -> list[str]:
        return sorted(self._registry.known_nodes())

    def node_count(self) -> int:
        return len(self._registry.known_nodes())
