from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class RetryDecision:
    should_retry: bool
    delay_seconds: float


class RetryPolicy:
    """
    Deterministic async retry policy for Gate execution paths.

    Only ``retryable_exceptions`` are retried; everything else propagates
    immediately so non-transient failures are not masked by retries.
    """

    def __init__(
        self,
        max_attempts: int = 3,
        delay_seconds: float = 0.1,
        backoff_multiplier: float = 1.0,
        retryable_exceptions: tuple[type[BaseException], ...] = (TimeoutError,),
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if delay_seconds < 0:
            raise ValueError("delay_seconds must be >= 0")
        if backoff_multiplier < 1.0:
            raise ValueError("backoff_multiplier must be >= 1.0")

        self.max_attempts = max_attempts
        self.delay_seconds = delay_seconds
        self.backoff_multiplier = backoff_multiplier
        self.retryable_exceptions = retryable_exceptions

    def decision_for(self, *, attempt: int, exc: BaseException) -> RetryDecision:
        if attempt < 1:
            raise ValueError("attempt must be >= 1")

        is_retryable = isinstance(exc, self.retryable_exceptions)
        if not is_retryable or attempt >= self.max_attempts:
            return RetryDecision(should_retry=False, delay_seconds=0.0)

        delay = self.delay_seconds * (self.backoff_multiplier ** (attempt - 1))
        return RetryDecision(should_retry=True, delay_seconds=delay)

    async def run(self, func: Callable[[], Awaitable[object]]) -> object:
        last_exc: BaseException | None = None

        for attempt in range(1, self.max_attempts + 1):
            try:
                return await func()
            except BaseException as exc:
                last_exc = exc
                decision = self.decision_for(attempt=attempt, exc=exc)
                if not decision.should_retry:
                    raise
                if decision.delay_seconds > 0:
                    await asyncio.sleep(decision.delay_seconds)

        assert last_exc is not None
        raise last_exc
