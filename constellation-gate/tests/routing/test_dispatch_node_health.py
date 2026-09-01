"""Only an unreachable worker is evidence that the worker is down.

BEHAVIOUR PINNED DELIBERATELY. An early dispatcher caught ``httpx.TransportError``
and marked the node unhealthy. ``httpx.TimeoutException`` is a SUBCLASS of
``httpx.TransportError``, so a worker that was merely slow got ejected from
routing on one timeout -- and once unhealthy it stops being resolved, so the
slowness became an outage.

The classification now belongs to Gate_SDK, which raises a distinct type per
outcome. This module proves Gate still acts on that distinction correctly, and
that it does so by catching a type rather than by reading a message. These cases
also carry forward the intent of the deleted ``test_worker_transport.py``: the
Gate-local adapter is gone, but "down vs slow vs answered badly" is still Gate's
routing decision and is still proven here.

The failures are induced through a real ``httpx.MockTransport`` rather than a
hand-written fake client, so the SDK's own httpx handling runs for real.
"""

from __future__ import annotations

import httpx
import pytest
from constellation_node_sdk.gate_authority import (
    GateDispatchError,
    WorkerConnectionError,
    WorkerHTTPError,
    WorkerResponseError,
    WorkerTimeoutError,
)
from constellation_node_sdk.transport.packet import create_transport_packet

from constellation_gate.resilience.deadline import Deadline
from constellation_gate.routing.dispatch import Dispatcher
from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry


def _registry() -> NodeRegistry:
    registry = NodeRegistry()
    registry.register_node(
        "worker",
        NodeRegistration(
            node_name="worker",
            internal_url="http://worker:8000",
            supported_actions=("score",),
            timeout_ms=30_000,
        ),
    )
    return registry


def _packet():
    return create_transport_packet(
        action="score",
        payload={"a": 1},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _dispatch(registry: NodeRegistry, handler) -> None:
    async with _client(handler) as client:
        dispatcher = Dispatcher(local_node="gate", registry=registry, client=client)
        await dispatcher.dispatch(_packet(), deadline=Deadline(30.0))


def _raises(exc: Exception):
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    return handler


def _responds(status_code: int, body):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=status_code, json=body, request=request)

    return handler


@pytest.mark.asyncio
async def test_unreachable_worker_is_marked_unhealthy() -> None:
    registry = _registry()
    with pytest.raises(WorkerConnectionError):
        await _dispatch(registry, _raises(httpx.ConnectError("refused")))

    assert registry.snapshot()["worker"].healthy is False


@pytest.mark.asyncio
async def test_a_slow_worker_is_not_marked_unhealthy() -> None:
    """A timeout says 'no answer yet', not 'this node is down'."""
    registry = _registry()
    with pytest.raises(WorkerTimeoutError) as info:
        await _dispatch(registry, _raises(httpx.ReadTimeout("slow")))

    assert not isinstance(info.value, WorkerConnectionError), (
        "a timeout must stay distinguishable from an unreachable node"
    )
    assert registry.snapshot()["worker"].healthy is True, (
        "a single slow response must not eject a working node from routing"
    )


@pytest.mark.asyncio
async def test_an_http_error_does_not_mark_the_worker_unhealthy() -> None:
    """A 500 from the worker is an upstream bug, not an unreachable node."""
    registry = _registry()
    with pytest.raises(WorkerHTTPError) as info:
        await _dispatch(registry, _responds(500, {}))

    assert info.value.status_code == 500
    assert registry.snapshot()["worker"].healthy is True


@pytest.mark.asyncio
async def test_an_uninterpretable_body_does_not_mark_the_worker_unhealthy() -> None:
    """A 200 carrying something that is not a canonical packet is still not 'down'."""
    registry = _registry()
    with pytest.raises(WorkerResponseError):
        await _dispatch(registry, _responds(200, {"not": "a packet"}))

    assert registry.snapshot()["worker"].healthy is True


@pytest.mark.asyncio
async def test_every_dispatch_failure_is_a_typed_sdk_dispatch_error() -> None:
    """Gate must never need httpx or a message substring to classify an outcome."""
    cases = [
        _raises(httpx.ConnectError("x")),
        _raises(httpx.ReadTimeout("x")),
        _responds(503, {}),
        _responds(200, {"not": "a packet"}),
    ]
    for handler in cases:
        registry = _registry()
        with pytest.raises(GateDispatchError):
            await _dispatch(registry, handler)


@pytest.mark.asyncio
async def test_a_dispatch_failure_is_attributed_to_the_resolved_node() -> None:
    """The SDK is told a target and never resolves one, so Gate supplies the name."""
    registry = _registry()
    with pytest.raises(GateDispatchError) as info:
        await _dispatch(registry, _raises(httpx.ConnectError("refused")))

    assert info.value.node_name == "worker"


@pytest.mark.asyncio
async def test_the_underlying_cause_chain_survives_attribution() -> None:
    """Attribution must not overwrite or suppress the SDK's own ``__cause__``."""
    registry = _registry()
    with pytest.raises(WorkerConnectionError) as info:
        await _dispatch(registry, _raises(httpx.ConnectError("refused")))

    assert isinstance(info.value.__cause__, httpx.ConnectError), (
        "re-raising must preserve the httpx failure the SDK chained"
    )


@pytest.mark.asyncio
async def test_the_active_counter_is_released_on_every_failure_path() -> None:
    registry = _registry()
    for handler in (_raises(httpx.ConnectError("x")), _raises(httpx.ReadTimeout("x"))):
        registry.mark_healthy("worker")
        with pytest.raises(GateDispatchError):
            await _dispatch(registry, handler)

    assert registry.snapshot()["worker"].active_requests == 0
