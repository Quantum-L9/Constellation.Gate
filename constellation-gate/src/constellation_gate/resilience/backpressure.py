from __future__ import annotations

from dataclasses import dataclass


class BackpressureExceededError(RuntimeError):
    """Raised when Gate rejects work because queue pressure is too high."""


@dataclass(frozen=True)
class BackpressureDecision:
    allowed: bool
    reason: str | None = None


class BackpressurePolicy:
    """
    Deterministic backpressure guard based on queue depth.

    This is intentionally process-local and simple. It provides a stable
    decision contract that can later be backed by shared queue telemetry.
    """

    def __init__(self, *, max_queue_depth: int) -> None:
        if max_queue_depth < 1:
            raise ValueError("max_queue_depth must be >= 1")
        self._max_queue_depth = max_queue_depth

    @property
    def max_queue_depth(self) -> int:
        return self._max_queue_depth

    def decision_for(self, *, queue_depth: int) -> BackpressureDecision:
        if queue_depth < 0:
            raise ValueError("queue_depth must be >= 0")
        if queue_depth >= self._max_queue_depth:
            return BackpressureDecision(allowed=False, reason="queue_depth_limit_exceeded")
        return BackpressureDecision(allowed=True, reason=None)

    def enforce(self, *, queue_depth: int) -> None:
        decision = self.decision_for(queue_depth=queue_depth)
        if not decision.allowed:
            raise BackpressureExceededError(decision.reason or "backpressure_exceeded")
