from __future__ import annotations

import httpx


class AsyncHttpClientManager:
    """
    Startup-managed shared AsyncClient for Gate outbound calls.

    One Gate process should reuse one pooled client to avoid socket churn and
    to keep outbound concurrency bounded by pool configuration.
    """

    def __init__(
        self,
        *,
        max_connections: int = 256,
        max_keepalive_connections: int = 64,
        default_timeout_seconds: float = 30.0,
    ) -> None:
        if max_connections < 1:
            raise ValueError("max_connections must be >= 1")
        if max_keepalive_connections < 0:
            raise ValueError("max_keepalive_connections must be >= 0")
        if default_timeout_seconds <= 0:
            raise ValueError("default_timeout_seconds must be > 0")

        self._max_connections = max_connections
        self._max_keepalive_connections = max_keepalive_connections
        self._default_timeout_seconds = default_timeout_seconds
        self._client: httpx.AsyncClient | None = None

    async def startup(self) -> None:
        if self._client is not None:
            return

        self._client = httpx.AsyncClient(
            timeout=self._default_timeout_seconds,
            limits=httpx.Limits(
                max_connections=self._max_connections,
                max_keepalive_connections=self._max_keepalive_connections,
            ),
        )

    async def shutdown(self) -> None:
        if self._client is None:
            return
        await self._client.aclose()
        self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("AsyncHttpClientManager not started")
        return self._client

    @property
    def started(self) -> bool:
        return self._client is not None
