from __future__ import annotations

import pytest

from constellation_gate.runtime.http_client import AsyncHttpClientManager


@pytest.mark.asyncio
async def test_http_client_manager_startup_and_shutdown() -> None:
    manager = AsyncHttpClientManager(
        max_connections=10,
        max_keepalive_connections=5,
        default_timeout_seconds=3.0,
    )

    assert manager.started is False

    await manager.startup()
    assert manager.started is True
    assert manager.client is not None

    await manager.shutdown()
    assert manager.started is False


@pytest.mark.asyncio
async def test_http_client_manager_is_idempotent() -> None:
    manager = AsyncHttpClientManager()

    await manager.startup()
    first = manager.client
    await manager.startup()
    second = manager.client

    assert first is second

    await manager.shutdown()
