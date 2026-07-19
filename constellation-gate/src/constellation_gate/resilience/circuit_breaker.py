from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic
from typing import Any


class CircuitBreakerOpenError(RuntimeError):
    """Raised when execution is rejected because the breaker is open."""


@dataclass(frozen=True)
class CircuitBreakerState:
    state: str
    failure_count: int
    opened_at: float | None


class CircuitBreaker:
    """
    Deterministic circuit breaker with CLOSED, OPEN, and HALF_OPEN states.

    Behavior:
    - failures accumulate in CLOSED
    - threshold breach opens the breaker
    - after recovery_timeout_seconds, breaker enters HALF_OPEN
    - one success in HALF_OPEN closes the breaker
    - one failure in HALF_OPEN re-opens the breaker
    """

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        recovery_timeout_seconds: float = 30.0,
        time_source: Callable[[], float] = monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        if recovery_timeout_seconds <= 0:
            raise ValueError("recovery_timeout_seconds must be > 0")

        self._failure_threshold = failure_threshold
        self._recovery_timeout_seconds = recovery_timeout_seconds
        self._time_source = time_source
        self._state = "closed"
        self._failure_count = 0
        self._opened_at: float | None = None

    @property
    def snapshot(self) -> CircuitBreakerState:
        return CircuitBreakerState(
            state=self._state,
            failure_count=self._failure_count,
            opened_at=self._opened_at,
        )

    def before_call(self, *, now: float | None = None) -> None:
        current = self._time_source() if now is None else now

        if self._state == "open":
            assert self._opened_at is not None
            elapsed = current - self._opened_at
            if elapsed >= self._recovery_timeout_seconds:
                self._state = "half_open"
                return
            raise CircuitBreakerOpenError("circuit breaker is open")

    def record_success(self) -> None:
        self._state = "closed"
        self._failure_count = 0
        self._opened_at = None

    def record_failure(self, *, now: float | None = None) -> None:
        current = self._time_source() if now is None else now

        if self._state == "half_open":
            self._trip_open(now=current)
            return

        self._failure_count += 1
        if self._failure_count >= self._failure_threshold:
            self._trip_open(now=current)

    def _trip_open(self, *, now: float) -> None:
        self._state = "open"
        self._opened_at = now

    async def run(self, func: Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any) -> Any:
        self.before_call()
        try:
            result = await func(*args, **kwargs)
        except Exception:
            self.record_failure()
            raise
        self.record_success()
        return result
