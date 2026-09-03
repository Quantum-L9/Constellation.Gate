from __future__ import annotations

import asyncio
import logging

import httpx

from constellation_gate.routing.node_registry import NodeRegistry

logger = logging.getLogger("constellation_gate.routing.health_monitor")


class HealthMonitor:
    """
    Periodically probes registered nodes and updates registry health state.

    This loop is the only path that restores a worker to routing after the
    dispatcher marked it unhealthy on a connection failure (other than the
    worker re-registering itself). It therefore must not die: a probe that
    raises is logged and counted as unhealthy, never propagated out of the
    loop.
    """

    def __init__(
        self,
        registry: NodeRegistry,
        *,
        interval_seconds: float = 15.0,
        client: httpx.AsyncClient | None = None,
        probe_timeout_seconds: float = 5.0,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be > 0")
        if probe_timeout_seconds <= 0:
            raise ValueError("probe_timeout_seconds must be > 0")

        self._registry = registry
        self._interval_seconds = interval_seconds
        self._client = client
        self._probe_timeout_seconds = probe_timeout_seconds
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self.probe_rounds = 0

    @property
    def interval_seconds(self) -> float:
        return self._interval_seconds

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.running:
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
            if healthy == registration.healthy:
                continue
            if healthy:
                self._registry.mark_healthy(node_name)
                logger.info("gate.health.restored node=%s", node_name)
            else:
                self._registry.mark_unhealthy(node_name)
                logger.warning("gate.health.lost node=%s", node_name)
        self.probe_rounds += 1

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.probe_once()
            except Exception:  # noqa: BLE001
                # The loop must outlive any one probe round.
                logger.exception("gate.health.probe_round_failed")
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval_seconds)
            except TimeoutError:
                continue

    async def _probe_node(self, *, url: str) -> bool:
        try:
            if self._client is not None:
                response = await self._client.get(url, timeout=self._probe_timeout_seconds)
                return response.status_code == 200

            async with httpx.AsyncClient(timeout=self._probe_timeout_seconds) as client:
                response = await client.get(url)
                return response.status_code == 200
        except httpx.HTTPError:
            return False
        except Exception:  # noqa: BLE001
            # An unexpected probe error is "not healthy", not a crash of the loop.
            logger.exception("gate.health.probe_error url=%s", url)
            return False
