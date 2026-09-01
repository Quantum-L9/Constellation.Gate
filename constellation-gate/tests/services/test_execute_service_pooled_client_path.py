"""Gate's pooled client is the one the SDK dispatches through, and Gate keeps it.

Two separable claims, both previously unproven:

1. The pooled client is actually USED. A dispatch that quietly opened a client of
   its own would still pass a test that only asserted the response, while paying
   a TCP handshake per packet in production.
2. The pooled client SURVIVES. ``GateDispatchTransport`` closes only a client it
   created itself; if it ever closed Gate's, the first dispatch would succeed and
   every later one would fail on a closed pool.

The client here is a real ``httpx.AsyncClient`` subclass -- real connection
pooling, real request path -- that counts its own use, so neither claim rests on
a stand-in that cannot behave like the production object.
"""

from __future__ import annotations

import httpx
import pytest
from constellation_node_sdk.transport.packet import create_transport_packet
from constellation_node_sdk.transport.provenance import RoutingProvenance
from support.sdk_worker import SdkWorker

from constellation_gate.routing.dispatch import Dispatcher
from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry
from constellation_gate.runtime.http_client import AsyncHttpClientManager
from constellation_gate.runtime.node_limits import PerNodeLimiterManager


class CountingAsyncClient(httpx.AsyncClient):
    """A real pooled client that records how often it was dispatched through."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.post_calls = 0

    async def post(self, *args, **kwargs):  # type: ignore[override]
        self.post_calls += 1
        return await super().post(*args, **kwargs)


def _registry() -> NodeRegistry:
    registry = NodeRegistry()
    registry.register_node(
        "score",
        NodeRegistration(
            node_name="score",
            internal_url="http://score:8000",
            supported_actions=("score",),
            max_concurrent=2,
            timeout_ms=15_000,
        ),
    )
    return registry


def _packet(entity_id: str = "42"):
    return create_transport_packet(
        action="score",
        payload={"entity_id": entity_id},
        tenant="tenant-a",
        destination_node="gate",
        source_node="orchestrator",
        reply_to="orchestrator",
        provenance=RoutingProvenance(
            origin_kind="node",
            requested_action="score",
            resolved_by_gate=False,
            original_source_node="orchestrator",
        ),
    )


def _worker() -> SdkWorker:
    return SdkWorker(
        node_name="score",
        action="score",
        handler=lambda org_id, payload: {"status": "completed"},
    )


@pytest.mark.asyncio
async def test_dispatcher_uses_injected_pooled_client_path() -> None:
    worker = _worker()

    async with CountingAsyncClient(transport=worker.transport()) as pooled_client:
        dispatcher = Dispatcher(
            local_node="gate",
            registry=_registry(),
            client=pooled_client,
            node_limits=PerNodeLimiterManager(),
        )

        result = await dispatcher.dispatch(_packet())

        assert result.payload["status"] == "completed"
        assert pooled_client.post_calls == 1, "the dispatch bypassed Gate's pooled client"

    manager = AsyncHttpClientManager()
    assert manager.started is False


@pytest.mark.asyncio
async def test_the_pooled_client_is_reused_across_dispatches_and_never_closed() -> None:
    """The SDK must not close a client it did not create."""
    worker = _worker()

    async with CountingAsyncClient(transport=worker.transport()) as pooled_client:
        dispatcher = Dispatcher(
            local_node="gate",
            registry=_registry(),
            client=pooled_client,
            node_limits=PerNodeLimiterManager(),
        )

        for entity_id in ("1", "2", "3"):
            await dispatcher.dispatch(_packet(entity_id))
            assert pooled_client.is_closed is False, (
                "the dispatch transport closed Gate's pooled client; every "
                "subsequent dispatch would fail on a closed pool"
            )

        assert pooled_client.post_calls == 3
        assert worker.request_count == 3

    assert pooled_client.is_closed is True, "Gate's own lifecycle still closes it"


@pytest.mark.asyncio
async def test_the_deferred_provider_resolves_the_pool_at_dispatch_time() -> None:
    """The pool does not exist at wiring time, so the provider is consulted late.

    A dispatcher that resolved the client in ``__init__`` would capture the
    pre-startup ``None`` forever and silently open a client per dispatch.
    """
    worker = _worker()
    holder: dict[str, httpx.AsyncClient | None] = {"client": None}

    dispatcher = Dispatcher(
        local_node="gate",
        registry=_registry(),
        client_provider=lambda: holder["client"],
        node_limits=PerNodeLimiterManager(),
    )

    async with CountingAsyncClient(transport=worker.transport()) as pooled_client:
        # Wired before the pool existed; only now does it become available.
        holder["client"] = pooled_client

        await dispatcher.dispatch(_packet())

        assert pooled_client.post_calls == 1, (
            "the dispatcher resolved its client too early to see the pool"
        )
