from __future__ import annotations

import math
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
    Deterministic fixed-window rate limiter keyed by arbitrary subject.

    Time is partitioned into contiguous windows of ``window_seconds`` aligned to
    the clock origin. Each key may issue up to ``max_requests`` within a window;
    the counter resets when a new window begins. Intentionally process-local and
    predictable, suitable for single-process Gate admission control and tests. A
    shared backend can replace it later without changing the decision contract.
    """

    def __init__(self, *, max_requests: int, window_seconds: float) -> None:
        if max_requests < 1:
            raise ValueError("max_requests must be >= 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")

        self._max_requests = max_requests
        self._window_seconds = window_seconds
        # key -> (window_index, count)
        self._counters: dict[str, tuple[int, int]] = {}

    @property
    def max_requests(self) -> int:
        return self._max_requests

    @property
    def window_seconds(self) -> float:
        return self._window_seconds

    def _window_index(self, now: float) -> int:
        return math.floor(now / self._window_seconds)

    def _count_for(self, key: str, window_index: int) -> int:
        stored = self._counters.get(key)
        if stored is None or stored[0] != window_index:
            return 0
        return stored[1]

    def _retry_after(self, window_index: int, now: float) -> float:
        window_end = (window_index + 1) * self._window_seconds
        return max(0.0, window_end - now)

    def decision_for(self, *, key: str, now: float | None = None) -> RateLimitDecision:
        current = monotonic() if now is None else now
        window_index = self._window_index(current)
        count = self._count_for(key, window_index)

        if count < self._max_requests:
            return RateLimitDecision(allowed=True, retry_after_seconds=0.0)
        return RateLimitDecision(
            allowed=False,
            retry_after_seconds=self._retry_after(window_index, current),
        )

    def allow(self, *, key: str, now: float | None = None) -> None:
        current = monotonic() if now is None else now
        window_index = self._window_index(current)
        count = self._count_for(key, window_index)

        if count >= self._max_requests:
            retry_after = self._retry_after(window_index, current)
            raise RateLimitExceededError(
                f"rate limit exceeded for key={key!r}; retry after {retry_after:.3f}s"
            )

        self._counters[key] = (window_index, count + 1)

    def clear(self) -> None:
        self._counters.clear()
