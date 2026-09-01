"""Packet replay guard with a real, enforced window (ADR-GATE-011).

If Gate declares a replay window of N seconds, then ``check_and_record`` must
enforce that window as part of ordinary execution. A separate ``prune()`` that
nothing on the hot path is guaranteed to call does not implement the stated
invariant: it leaves the window advertised but unenforced, and lets the seen-set
grow without bound for the life of the process.

Expiry therefore happens inside ``check_and_record`` itself:

- packet id unseen                  -> accept and record
- packet id seen inside the window  -> reject
- packet id seen only before the window expired -> expire and accept

The clock is injectable so the window is testable deterministically rather than
by sleeping.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta


class ReplayGuard:
    def __init__(
        self,
        window_seconds: int = 300,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        self.window = timedelta(seconds=window_seconds)
        self._clock = clock
        self._seen: dict[str, datetime] = {}

    def check_and_record(self, packet_id: str) -> None:
        now = self._clock()

        # Expire on the hot path so the advertised window is the behaviour, and
        # so seen-state stays bounded by arrival rate * window rather than by
        # total process uptime.
        self._expire(now)

        seen_at = self._seen.get(packet_id)
        if seen_at is not None and now - seen_at <= self.window:
            raise ValueError("replay detected")

        self._seen[packet_id] = now

    def prune(self) -> None:
        """Expire stale entries out of band. Kept for operators; not required."""
        self._expire(self._clock())

    def _expire(self, now: datetime) -> None:
        window = self.window
        expired = [key for key, seen_at in self._seen.items() if now - seen_at > window]
        for key in expired:
            del self._seen[key]

    def __len__(self) -> int:
        return len(self._seen)
