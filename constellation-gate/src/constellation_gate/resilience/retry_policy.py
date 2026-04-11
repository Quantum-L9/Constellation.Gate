from __future__ import annotations

import asyncio


class RetryPolicy:
    def __init__(self, max_attempts: int = 3, delay_seconds: float = 0.1) -> None:
        self.max_attempts = max_attempts
        self.delay_seconds = delay_seconds

    async def run(self, func, *args, **kwargs):
        last_exc = None
        for _ in range(self.max_attempts):
            try:
                return await func(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                await asyncio.sleep(self.delay_seconds)
        raise last_exc
