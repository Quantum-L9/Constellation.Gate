from __future__ import annotations

import asyncio
from dataclasses import dataclass


class NodeLimitExceededError(RuntimeError):
    """Raised when a node has reached its configured concurrent execution limit."""


@dataclass(frozen=True)
class NodeLimitSnapshot:
    node_name: str
    max_concurrent: int
    active: int


class PerNodeLimiterManager:
    """
    Deterministic per-node concurrency limiter.

    Gate uses this to prevent one hot worker node from being overloaded by
    concurrent dispatches inside a single Gate process.
    """

    def __init__(self) -> None:
        self._limits: dict[str, int] = {}
        self._active: dict[str, int] = {}

    def ensure_node_limit(self, node_name: str, max_concurrent: int) -> None:
        normalized = node_name.strip().lower()
        if not normalized:
            raise ValueError("node_name must not be empty")
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")

        self._limits[normalized] = max_concurrent
        self._active.setdefault(normalized, 0)

    async def acquire(self, node_name: str) -> None:
        normalized = node_name.strip().lower()
        if normalized not in self._limits:
            raise LookupError(f"node limit not configured: {normalized}")

        if self._active[normalized] >= self._limits[normalized]:
            raise NodeLimitExceededError(f"node concurrency limit reached: {normalized}")

        self._active[normalized] += 1
        await asyncio.sleep(0)

    def release(self, node_name: str) -> None:
        normalized = node_name.strip().lower()
        if normalized not in self._active:
            raise LookupError(f"node limit not configured: {normalized}")
        self._active[normalized] = max(0, self._active[normalized] - 1)

    def active_count(self, node_name: str) -> int:
        normalized = node_name.strip().lower()
        return self._active.get(normalized, 0)

    def snapshot(self, node_name: str) -> NodeLimitSnapshot:
        normalized = node_name.strip().lower()
        if normalized not in self._limits:
            raise LookupError(f"node limit not configured: {normalized}")
        return NodeLimitSnapshot(
            node_name=normalized,
            max_concurrent=self._limits[normalized],
            active=self._active[normalized],
        )
