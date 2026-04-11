from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from time import monotonic


class RateLimitExceededError(RuntimeError):
    """Raised when a caller exceeds the configured admission rate."""


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: float


class FixedWindowRateLimiter:
    """
    Deterministic sliding-window rate limiter keyed by arbitrary subject.

    This implementation is intentionally process-local and predictable. It is
    suitable for single-process Gate admission control and for tests. A shared
    backend can replace it later without changing the decision contract.
    """

    def __init__(self, *, max_requests: int, window_seconds: float) -> None:
        if max_requests < 1:
            raise ValueError("max_requests must be >= 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")

        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._events: dict[str, deque[float]] = {}

    @property
    def max_requests(self) -> int:
        return self._max_requests

    @property
    def window_seconds(self) -> float:
        return self._window_seconds

    def decision_for(self, *, key: str, now: float | None = None) -> RateLimitDecision:
        current = monotonic() if now is None else now
        queue = self._events.setdefault(key, deque())
        self._prune(queue, now=current)

        if len(queue) < self._max_requests:
            return RateLimitDecision(allowed=True, retry_after_seconds=0.0)

        oldest = queue[0]
        retry_after = max(0.0, self._window_seconds - (current - oldest))
        return RateLimitDecision(allowed=False, retry_after_seconds=retry_after)

    def allow(self, *, key: str, now: float | None = None) -> None:
        current = monotonic() if now is None else now
        queue = self._events.setdefault(key, deque())
        self._prune(queue, now=current)

        if len(queue) >= self._max_requests:
            oldest = queue[0]
            retry_after = max(0.0, self._window_seconds - (current - oldest))
            raise RateLimitExceededError(
                f"rate limit exceeded for key={key!r}; retry after {retry_after:.3f}s"
            )

        queue.append(current)

    def clear(self) -> None:
        self._events.clear()

    def _prune(self, queue: deque[float], *, now: float) -> None:
        while queue and (now - queue[0]) >= self._window_seconds:
            queue.popleft()
