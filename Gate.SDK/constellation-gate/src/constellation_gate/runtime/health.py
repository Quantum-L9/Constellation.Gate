from __future__ import annotations

from typing import Any


def health_status(*, service_name: str, node_name: str, environment: str) -> dict[str, Any]:
    return {
        "status": "healthy",
        "service_name": service_name,
        "node_name": node_name,
        "environment": environment,
    }
