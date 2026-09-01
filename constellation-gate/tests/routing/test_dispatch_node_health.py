"""Only an unreachable worker is evidence that the worker is down.

BEHAVIOUR CHANGE, pinned here deliberately. The previous dispatcher caught
``httpx.TransportError`` and marked the node unhealthy. ``httpx.TimeoutException``
is a SUBCLASS of ``httpx.TransportError``, so a worker that was merely slow got
ejected from routing on one timeout -- and once unhealthy it stops being
resolved, so the slowness became an outage. The typed transport errors let the
dispatcher separate "down" from "slow", and only the first changes health.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from constellation_node_sdk.transport.packet import create_transport_packet

from constellation_gate.resilience.deadline import Deadline
from constellation_gate.routing.dispatch import Dispatcher
from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry
from constellation_gate.routing.worker_transport import (
    WorkerResponseError,
    WorkerTimeoutError,
    WorkerUnreachableError,
)


class FailingClient:
    def __init__(self, exc: Exception | None = None, response: Any = None) -> None:
        self._exc = exc
        self._response = response

    async def post(self, url: str, json: dict, headers: dict, timeout: float):
        if self._exc is not None:
            raise self._exc
        return self._response


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


async def _dispatch(registry: NodeRegistry, client: Any) -> None:
    dispatcher = Dispatcher(local_node="gate", registry=registry, client=client)
    await dispatcher.dispatch(_packet(), deadline=Deadline(30.0))


@pytest.mark.asyncio
async def test_unreachable_worker_is_marked_unhealthy() -> None:
    registry = _registry()
    with pytest.raises(WorkerUnreachableError):
        await _dispatch(registry, FailingClient(httpx.ConnectError("refused")))

    assert registry.snapshot()["worker"].healthy is False


@pytest.mark.asyncio
async def test_a_slow_worker_is_not_marked_unhealthy() -> None:
    """A timeout says 'no answer yet', not 'this node is down'."""
    registry = _registry()
    with pytest.raises(WorkerTimeoutError):
        await _dispatch(registry, FailingClient(httpx.ReadTimeout("slow")))

    assert registry.snapshot()["worker"].healthy is True, (
        "a single slow response must not eject a working node from routing"
    )


@pytest.mark.asyncio
async def test_a_bad_response_does_not_mark_the_worker_unhealthy() -> None:
    """A 500 from the worker is an upstream bug, not an unreachable node."""
    registry = _registry()
    request = httpx.Request("POST", "http://worker:8000/v1/execute")
    response = httpx.Response(status_code=500, json={}, request=request)

    with pytest.raises(WorkerResponseError):
        await _dispatch(registry, FailingClient(response=response))

    assert registry.snapshot()["worker"].healthy is True


@pytest.mark.asyncio
async def test_the_active_counter_is_released_on_every_failure_path() -> None:
    registry = _registry()
    for exc in (httpx.ConnectError("x"), httpx.ReadTimeout("x")):
        registry.mark_healthy("worker")
        with pytest.raises(Exception):  # noqa: B017 -- category asserted above
            await _dispatch(registry, FailingClient(exc))
        assert registry.snapshot()["worker"].active_requests == 0
