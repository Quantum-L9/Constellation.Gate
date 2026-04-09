from __future__ import annotations

import httpx

from constellation_gate.routing.health_monitor import HealthMonitor
from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry


class FakeHealthClient:
    def __init__(self, responses: dict[str, int]) -> None:
        self._responses = responses

    async def get(self, url: str, timeout: float) -> httpx.Response:
        status_code = self._responses[url]
        request = httpx.Request("GET", url)
        return httpx.Response(status_code=status_code, request=request)


def test_health_monitor_marks_nodes_healthy_and_unhealthy() -> None:
    registry = NodeRegistry()
    registry.register_node(
        "enrich",
        NodeRegistration(
            node_name="enrich",
            internal_url="http://enrich:8000",
            supported_actions=("enrich",),
            health_endpoint="/v1/health",
        ),
    )
    registry.register_node(
        "score",
        NodeRegistration(
            node_name="score",
            internal_url="http://score:8000",
            supported_actions=("score",),
            health_endpoint="/v1/health",
        ),
    )

    client = FakeHealthClient(
        {
            "http://enrich:8000/v1/health": 200,
            "http://score:8000/v1/health": 503,
        }
    )
    monitor = HealthMonitor(registry, interval_seconds=60.0, client=client)

    __import__("asyncio").run(monitor.probe_once())

    snapshot = registry.snapshot()
    assert snapshot["enrich"].healthy is True
    assert snapshot["score"].healthy is False
