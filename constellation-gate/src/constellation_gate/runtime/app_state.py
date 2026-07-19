from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AppState:
    services: dict[str, Any] = field(default_factory=dict)
    http_client_manager: Any = None
    node_limiter_manager: Any = None
    lifecycle_manager: Any = None

    def register(self, name: str, service: Any) -> None:
        self.services[name] = service

    def get(self, name: str) -> Any:
        if name not in self.services:
            raise KeyError(f"service not found: {name}")
        return self.services[name]

    def attach_runtime(
        self,
        *,
        http_client_manager: Any = None,
        node_limiter_manager: Any = None,
        lifecycle_manager: Any = None,
    ) -> None:
        self.http_client_manager = http_client_manager
        self.node_limiter_manager = node_limiter_manager
        self.lifecycle_manager = lifecycle_manager
