from __future__ import annotations

import pytest

from constellation_gate.runtime.node_limits import NodeLimitExceededError, PerNodeLimiterManager


@pytest.mark.asyncio
async def test_node_limits_acquire_release_tracks_active_count() -> None:
    manager = PerNodeLimiterManager()
    manager.ensure_node_limit("score", 2)

    await manager.acquire("score")
    await manager.acquire("score")

    assert manager.active_count("score") == 2

    manager.release("score")
    assert manager.active_count("score") == 1

    manager.release("score")
    assert manager.active_count("score") == 0


@pytest.mark.asyncio
async def test_node_limits_reject_when_limit_reached() -> None:
    manager = PerNodeLimiterManager()
    manager.ensure_node_limit("score", 1)

    await manager.acquire("score")

    with pytest.raises(NodeLimitExceededError):
        await manager.acquire("score")
