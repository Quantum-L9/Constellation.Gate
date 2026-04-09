from __future__ import annotations

import asyncio

import httpx

from constellation_gate.routing.node_registry import NodeRegistry


class HealthMonitor:
    """
    Periodically probes registered nodes and updates registry health state.
    """

    def __init__(
        self,
        registry: NodeRegistry,
        *,
        interval_seconds: float = 15.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be > 0")

        self._registry = registry
        self._interval_seconds = interval_seconds
        self._client = client
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            await self._task
            self._task = None

    async def probe_once(self) -> None:
        snapshot = self._registry.snapshot()
        for node_name, registration in snapshot.items():
            healthy = await self._probe_node(
                url=f"{registration.internal_url}{registration.health_endpoint}"
            )
            if healthy:
                self._registry.mark_healthy(node_name)
            else:
                self._registry.mark_unhealthy(node_name)

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            await self.probe_once()
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval_seconds)
            except TimeoutError:
                continue

    async def _probe_node(self, *, url: str) -> bool:
        try:
            if self._client is not None:
                response = await self._client.get(url, timeout=5.0)
                return response.status_code == 200

            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(url)
                return response.status_code == 200
        except httpx.TransportError:
            return False
