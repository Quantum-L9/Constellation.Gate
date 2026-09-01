"""One monotonic execution deadline per canonical packet (ADR-GATE-008).

Gate receives exactly one packet-level execution budget (``header.timeout_ms``).
That budget is converted into a single monotonic deadline at ingress, and every
subsequent stage -- admission waits, retry sleeps, worker transport, response
validation -- draws from the same remaining budget.

The clock is ``time.monotonic`` and never the wall clock: wall-clock jumps (NTP
correction, container suspend) must not extend or truncate a packet budget.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from constellation_node_sdk.transport.packet import TransportPacket


class DeadlineExceeded(TimeoutError):
    """Raised when the single packet execution budget is exhausted.

    Subclasses :class:`TimeoutError` so existing timeout handling keeps working,
    while remaining distinguishable from a per-attempt transport timeout.
    """


class Deadline:
    """A single monotonic execution budget shared by every stage of one packet."""

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

    def elapsed_seconds(self) -> float:
        return max(0.0, self._clock() - self._started_at)

    def remaining_seconds(self) -> float:
        """Remaining budget, floored at 0.0 (never negative)."""
        return max(0.0, self._total_seconds - self.elapsed_seconds())

    def expired(self) -> bool:
        return self.remaining_seconds() <= 0.0

    def raise_if_expired(self, *, stage: str) -> None:
        if self.expired():
            raise DeadlineExceeded(
                f"packet execution deadline exceeded before {stage} "
                f"(budget {self._total_seconds:.3f}s)"
            )

    def bounded_by(self, cap_seconds: float | None) -> float:
        """Return ``min(remaining, cap)`` -- the budget a downstream attempt gets.

        A downstream network attempt is never allowed a fresh full timeout: it
        receives whatever of the one packet budget is still unspent, further
        capped by any node-configured ceiling.
        """
        remaining = self.remaining_seconds()
        if cap_seconds is None:
            return remaining
        if cap_seconds <= 0:
            raise ValueError("cap_seconds must be > 0 when provided")
        return min(remaining, float(cap_seconds))


def deadline_for_packet(
    packet: TransportPacket,
    *,
    default_timeout_ms: int = 30_000,
    clock: Callable[[], float] = time.monotonic,
) -> Deadline:
    """Derive the one monotonic deadline governing this packet's execution."""
    timeout_ms = packet.header.timeout_ms or default_timeout_ms
    return Deadline(timeout_ms / 1000.0, clock=clock)
