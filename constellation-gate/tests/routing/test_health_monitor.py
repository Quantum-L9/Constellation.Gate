from __future__ import annotations

import asyncio

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


class MutableHealthClient:
    """Answers change between probe rounds, like a worker that restarts."""

    def __init__(self) -> None:
        self.responses: dict[str, int | Exception] = {}
        self.calls = 0

    async def get(self, url: str, timeout: float) -> httpx.Response:
        self.calls += 1
        outcome = self.responses[url]
        if isinstance(outcome, Exception):
            raise outcome
        return httpx.Response(status_code=outcome, request=httpx.Request("GET", url))


def _eie_registry() -> NodeRegistry:
    registry = NodeRegistry()
    registry.register_node(
        "enrichment-engine",
        NodeRegistration(
            node_name="enrichment-engine",
            internal_url="http://enrichment-engine:8000",
            supported_actions=("converge",),
            health_endpoint="/api/v1/health",
            metadata={"owner": "eie"},
        ),
    )
    return registry


def test_health_monitor_restores_a_worker_the_dispatcher_marked_unhealthy() -> None:
    """The re-probe is the only automatic path back to routing after a connection failure."""
    registry = _eie_registry()
    registry.mark_unhealthy("enrichment-engine")
    client = MutableHealthClient()
    url = "http://enrichment-engine:8000/api/v1/health"
    client.responses[url] = httpx.ConnectError("refused", request=httpx.Request("GET", url))
    monitor = HealthMonitor(registry, interval_seconds=60.0, client=client)

    asyncio.run(monitor.probe_once())
    assert registry.snapshot()["enrichment-engine"].healthy is False

    client.responses[url] = 200
    asyncio.run(monitor.probe_once())
    assert registry.snapshot()["enrichment-engine"].healthy is True
    assert monitor.probe_rounds == 2


def test_probe_loop_survives_an_unexpected_probe_error() -> None:
    registry = _eie_registry()
    client = MutableHealthClient()
    url = "http://enrichment-engine:8000/api/v1/health"
    client.responses[url] = RuntimeError("boom")
    monitor = HealthMonitor(registry, interval_seconds=60.0, client=client)

    asyncio.run(monitor.probe_once())
    assert registry.snapshot()["enrichment-engine"].healthy is False

    client.responses[url] = 200
    asyncio.run(monitor.probe_once())
    assert registry.snapshot()["enrichment-engine"].healthy is True


async def _run_loop_rounds(monitor: HealthMonitor) -> None:
    await monitor.start()
    assert monitor.running
    for _ in range(50):
        if monitor.probe_rounds >= 2:
            break
        await asyncio.sleep(0.01)
    await monitor.stop()


def test_started_loop_probes_repeatedly_and_stops_cleanly() -> None:
    registry = _eie_registry()
    client = MutableHealthClient()
    client.responses["http://enrichment-engine:8000/api/v1/health"] = 200
    monitor = HealthMonitor(registry, interval_seconds=0.01, client=client)

    asyncio.run(_run_loop_rounds(monitor))

    assert monitor.probe_rounds >= 2
    assert monitor.running is False


def test_zero_interval_is_rejected() -> None:
    import pytest

    with pytest.raises(ValueError, match="interval_seconds"):
        HealthMonitor(NodeRegistry(), interval_seconds=0)
