"""The pooled client and per-node limiter must actually reach the Dispatcher.

Both were constructed at ASGI startup and then never passed in, so
AsyncHttpClientManager and PerNodeLimiterManager were thoroughly unit-tested and
completely dead in production: every dispatch opened and discarded its own
client, and the per-node concurrency limiter -- the authoritative admission gate
before a worker call -- never ran. Unit tests on the components could not see
this, because the gap was in the wiring between them.
"""

from __future__ import annotations

from functools import lru_cache

import pytest

from constellation_gate.api import dependencies as deps


@pytest.fixture(autouse=True)
def _clear_caches():
    deps.get_dispatcher.cache_clear()
    deps.get_http_client_manager.cache_clear()
    deps.get_node_limiter_manager.cache_clear()
    yield
    deps.get_dispatcher.cache_clear()
    deps.get_http_client_manager.cache_clear()
    deps.get_node_limiter_manager.cache_clear()


def test_dispatcher_receives_the_shared_node_limiter() -> None:
    dispatcher = deps.get_dispatcher()
    assert dispatcher._node_limits is deps.get_node_limiter_manager()


def test_dispatcher_receives_a_client_provider() -> None:
    dispatcher = deps.get_dispatcher()
    assert dispatcher._client_provider is not None


def test_client_provider_is_not_cached() -> None:
    """Caching it would freeze the pre-startup `None` and defeat the pool."""
    assert not isinstance(deps._pooled_client, type(lru_cache(lambda: None)))
    assert not hasattr(deps._pooled_client, "cache_clear")


def test_client_provider_returns_none_before_startup() -> None:
    """Non-ASGI callers stay on the per-call path rather than failing on wiring."""
    assert deps.get_http_client_manager().started is False
    assert deps._pooled_client() is None


@pytest.mark.asyncio
async def test_client_provider_resolves_the_pool_after_startup() -> None:
    manager = deps.get_http_client_manager()
    await manager.startup()
    try:
        assert deps._pooled_client() is manager.client
        # Resolution is per call, so a dispatcher built before startup still
        # picks the pool up afterwards.
        assert deps.get_dispatcher()._resolve_client() is manager.client
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_explicit_client_still_wins_over_the_provider() -> None:
    """Injected test clients must not be overridden by the pool."""
    from constellation_gate.routing.dispatch import Dispatcher

    sentinel = object()
    dispatcher = Dispatcher(
        local_node="gate",
        registry=deps.get_registry(),
        client=sentinel,  # type: ignore[arg-type]
        client_provider=deps._pooled_client,
    )
    assert dispatcher._resolve_client() is sentinel
