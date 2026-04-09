from __future__ import annotations

from datetime import datetime, timedelta, UTC


class ReplayGuard:
    def __init__(self, window_seconds: int = 300) -> None:
        self.window = timedelta(seconds=window_seconds)
        self._seen: dict[str, datetime] = {}

    def check_and_record(self, packet_id: str) -> None:
        now = datetime.now(UTC)
        if packet_id in self._seen:
            raise ValueError("replay detected")
        self._seen[packet_id] = now

    def prune(self) -> None:
        now = datetime.now(UTC)
        expired = [k for k, v in self._seen.items() if now - v > self.window]
        for k in expired:
            del self._seen[k]
