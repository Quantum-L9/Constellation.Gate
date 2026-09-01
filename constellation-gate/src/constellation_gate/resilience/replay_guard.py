"""Bounded, self-expiring transport replay guard.

Replay protection is about duplicate *transport* submission of the same
``packet_id``, distinct from semantic idempotency.

Two properties must hold on the hot path, and previously neither did:

1. The advertised replay window must be real. Expiry used to depend on an
   operator remembering to call ``prune()``; nothing did, so a packet_id was
   rejected forever and the window was decorative.
2. State must be bounded. An unpruned dict grows with every packet the process
   ever sees.

Expiry is therefore performed as part of ``check_and_record`` itself, and the
guard enforces a hard entry ceiling so a burst of unique packets cannot
exhaust memory before the window elapses.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta


class ReplayDetectedError(ValueError):
    """Raised when a packet_id is resubmitted inside the replay window."""


class ReplayGuard:
    def __init__(
        self,
        window_seconds: int = 300,
        *,
        max_entries: int = 100_000,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        self.window = timedelta(seconds=window_seconds)
        self.max_entries = max_entries
        self._clock = clock
        # Insertion-ordered: entries age in insertion order because the clock is
        # monotonic-forward, so expiry can stop at the first live entry.
        self._seen: OrderedDict[str, datetime] = OrderedDict()

    def check_and_record(self, packet_id: str) -> None:
        """Expire, then reject only if still inside the window, then record."""
        now = self._clock()
        self._expire(now)

        seen_at = self._seen.get(packet_id)
        if seen_at is not None and now - seen_at <= self.window:
            raise ReplayDetectedError("replay detected")

        self._seen.pop(packet_id, None)
        self._seen[packet_id] = now
        self._enforce_ceiling()

    def _expire(self, now: datetime) -> None:
        while self._seen:
            oldest_id, oldest_at = next(iter(self._seen.items()))
            if now - oldest_at <= self.window:
                return
            del self._seen[oldest_id]

    def _enforce_ceiling(self) -> None:
        while len(self._seen) > self.max_entries:
            self._seen.popitem(last=False)

    def prune(self) -> None:
        """Expire aged entries. Retained for operator/diagnostic use only --
        correctness no longer depends on anyone calling it."""
        self._expire(self._clock())

    def size(self) -> int:
        return len(self._seen)
