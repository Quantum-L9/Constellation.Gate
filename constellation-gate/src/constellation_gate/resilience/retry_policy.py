from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from constellation_gate.resilience.deadline import Deadline
from constellation_gate.resilience.replay_safety import DEFAULT_MAX_ATTEMPTS

T = TypeVar("T")


@dataclass(frozen=True)
class RetryDecision:
    should_retry: bool
    delay_seconds: float


class RetryPolicy:
    """
    Deterministic async retry policy for Gate execution paths.

    ``max_attempts`` defaults to 1 (ADR-GATE-007): a generic wrapper must not
    silently replay an arbitrary side-effect-capable worker operation. A caller
    that wants Gate-level replay must ask for it explicitly, having established
    that the action is replay-safe and carries a stable idempotency identity.

    Only ``retryable_exceptions`` are retried; everything else propagates
    immediately so non-transient failures are not masked by retries.

    When a ``Deadline`` is supplied, retries and their sleeps draw from that one
    packet budget: a retry never gets a fresh timeout, and Gate never sleeps past
    the deadline only to start an attempt that cannot finish.
    """

    def __init__(
        self,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
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

    async def run(
        self,
        func: Callable[[], Awaitable[T]],
        *,
        deadline: Deadline | None = None,
    ) -> T:
        last_exc: BaseException | None = None

        for attempt in range(1, self.max_attempts + 1):
            try:
                return await func()
            except BaseException as exc:
                last_exc = exc
                decision = self.decision_for(attempt=attempt, exc=exc)
                if not decision.should_retry:
                    raise
                if deadline is not None:
                    # A retry sleep spends the same packet budget as the work.
                    # If the sleep would consume what is left, the operation is
                    # already over -- surface the original failure rather than
                    # burning the remainder on an attempt that cannot complete.
                    if decision.delay_seconds >= deadline.remaining_seconds():
                        raise
                if decision.delay_seconds > 0:
                    await asyncio.sleep(decision.delay_seconds)
                if deadline is not None and deadline.expired():
                    raise

        assert last_exc is not None
        raise last_exc
