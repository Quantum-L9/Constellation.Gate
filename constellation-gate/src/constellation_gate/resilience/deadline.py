"""One monotonic packet deadline for a single Gate operation.

A packet's execution budget is created exactly once, immediately after ingress
validation, and every downstream stage consumes the *same* remaining budget:
workflow steps, dispatch, retry sleeps, and the actual worker network timeout.

This exists because an outer ``asyncio.wait_for`` is not evidence that the
worker transport is bounded. ``wait_for`` cancels the awaiting coroutine, but
the HTTP client underneath is still constructed with whatever timeout the
caller handed it -- historically a *fresh, full* per-node timeout on every
attempt. A retried operation could therefore consume N x timeout_ms of real
worker time inside a budget that claimed to be timeout_ms.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable


class DeadlineExceededError(TimeoutError):
    """Raised when the packet's monotonic execution budget is exhausted.

    Subclasses ``TimeoutError`` so existing timeout-shaped error mapping keeps
    working, while remaining distinguishable from a transport-level timeout.
    """


class PacketDeadline:
    """A single monotonic budget for one Gate operation.

    The clock is injectable so deadline behavior is deterministically testable
    without sleeping. It must be a *monotonic* source: wall-clock time can jump
    backwards and would silently extend a budget.
    """

    __slots__ = ("_clock", "_started_at", "_total_seconds")

    def __init__(
        self,
        total_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if total_seconds <= 0:
            raise ValueError("total_seconds must be > 0")
        self._clock = clock
        self._total_seconds = float(total_seconds)
        self._started_at = clock()

    @property
    def total_seconds(self) -> float:
        return self._total_seconds

    @property
    def elapsed_seconds(self) -> float:
        return self._clock() - self._started_at

    @property
    def remaining_seconds(self) -> float:
        """Remaining budget, floored at 0.0 (never negative, never refreshed)."""
        return max(0.0, self._total_seconds - self.elapsed_seconds)

    @property
    def expired(self) -> bool:
        return self.remaining_seconds <= 0.0

    def remaining_or_raise(self) -> float:
        """Return the remaining budget, or raise if it is already exhausted."""
        remaining = self.remaining_seconds
        if remaining <= 0.0:
            raise DeadlineExceededError(
                f"packet deadline exceeded after {self.elapsed_seconds:.3f}s "
                f"(budget {self._total_seconds:.3f}s)"
            )
        return remaining

    def budget_for(self, cap_seconds: float | None) -> float:
        """Downstream budget: ``min(remaining, cap)``.

        ``cap_seconds`` is the registered per-node ceiling. A worker may never
        be granted more than the packet has left, and never more than its own
        registered cap -- whichever is smaller wins.
        """
        remaining = self.remaining_or_raise()
        if cap_seconds is None:
            return remaining
        if cap_seconds <= 0:
            raise ValueError("cap_seconds must be > 0")
        return min(remaining, cap_seconds)

    async def sleep(self, seconds: float) -> None:
        """Sleep inside the budget.

        A retry backoff is not free time: it is charged against the same
        deadline. Sleeping past the deadline raises rather than silently
        overrunning it.
        """
        if seconds <= 0:
            self.remaining_or_raise()
            return
        remaining = self.remaining_or_raise()
        if seconds >= remaining:
            await asyncio.sleep(remaining)
            raise DeadlineExceededError("packet deadline exceeded during retry backoff")
        await asyncio.sleep(seconds)


def resolve_deadline(
    packet_timeout_seconds: float,
    *,
    clock: Callable[[], float] = time.monotonic,
) -> PacketDeadline:
    """Create the single deadline for a packet from its resolved timeout."""
    return PacketDeadline(packet_timeout_seconds, clock=clock)
