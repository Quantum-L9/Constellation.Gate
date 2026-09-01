"""The single monotonic deadline reaches the ACTUAL worker transport call.

`asyncio.wait_for` is not evidence. It cancels the coroutine that awaits, but
the HTTP client underneath is constructed with whatever timeout it was handed --
historically a fresh, full per-node timeout on every attempt. These tests assert
on the timeout the network client actually received.
"""

from __future__ import annotations

from typing import Any

import pytest
from constellation_node_sdk.transport.packet import create_transport_packet

from constellation_gate.resilience.deadline import DeadlineExceededError, PacketDeadline
from constellation_gate.routing.dispatch import Dispatcher
from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry


class TimeoutRecordingClient:
    """Records the timeout handed to the real network call, per attempt."""

    def __init__(self) -> None:
        self.timeouts: list[float] = []

    async def post(self, url: str, json: dict[str, Any], headers: dict[str, str], timeout: float):
        from httpx import Request, Response

        self.timeouts.append(timeout)
        response_packet = create_transport_packet(
            action=json["header"]["action"],
            payload={"ok": True},
            tenant="tenant-a",
            destination_node="gate",
            source_node="worker",
            reply_to="gate",
        )
        return Response(
            status_code=200,
            json=response_packet.model_dump_json_dict(),
            request=Request("POST", url),
        )


class FakeClock:
    def __init__(self) -> None:
        self.now = 500.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _registry(*, timeout_ms: int) -> NodeRegistry:
    registry = NodeRegistry()
    registry.register_node(
        "worker",
        NodeRegistration(
            node_name="worker",
            internal_url="http://worker:8000",
            supported_actions=("score",),
            timeout_ms=timeout_ms,
        ),
    )
    return registry


def _ingress() -> Any:
    return create_transport_packet(
        action="score",
        payload={"a": 1},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )


@pytest.mark.asyncio
async def test_worker_transport_receives_the_remaining_budget_not_the_node_cap() -> None:
    clock = FakeClock()
    deadline = PacketDeadline(30.0, clock=clock)
    client = TimeoutRecordingClient()
    dispatcher = Dispatcher(local_node="gate", registry=_registry(timeout_ms=30_000), client=client)

    # The packet has already spent 28 of its 30 seconds upstream.
    clock.advance(28.0)
    await dispatcher.dispatch(_ingress(), deadline=deadline)

    assert client.timeouts == [pytest.approx(2.0)], (
        "the worker must be granted only what the packet has left, "
        "not a fresh full node timeout"
    )


@pytest.mark.asyncio
async def test_node_cap_still_binds_when_it_is_the_smaller_of_the_two() -> None:
    clock = FakeClock()
    deadline = PacketDeadline(30.0, clock=clock)
    client = TimeoutRecordingClient()
    dispatcher = Dispatcher(local_node="gate", registry=_registry(timeout_ms=5_000), client=client)

    await dispatcher.dispatch(_ingress(), deadline=deadline)

    assert client.timeouts == [pytest.approx(5.0)]


@pytest.mark.asyncio
async def test_dispatch_refuses_to_start_once_the_budget_is_gone() -> None:
    clock = FakeClock()
    deadline = PacketDeadline(10.0, clock=clock)
    client = TimeoutRecordingClient()
    dispatcher = Dispatcher(local_node="gate", registry=_registry(timeout_ms=30_000), client=client)

    clock.advance(11.0)
    with pytest.raises(DeadlineExceededError):
        await dispatcher.dispatch(_ingress(), deadline=deadline)

    assert client.timeouts == [], "no worker call may be made on an exhausted budget"


@pytest.mark.asyncio
async def test_repeated_dispatches_share_one_shrinking_budget() -> None:
    """Two dispatches under one deadline must not each get a full budget."""
    clock = FakeClock()
    deadline = PacketDeadline(20.0, clock=clock)
    client = TimeoutRecordingClient()
    dispatcher = Dispatcher(local_node="gate", registry=_registry(timeout_ms=30_000), client=client)

    await dispatcher.dispatch(_ingress(), deadline=deadline)
    clock.advance(8.0)
    await dispatcher.dispatch(_ingress(), deadline=deadline)
    clock.advance(8.0)
    await dispatcher.dispatch(_ingress(), deadline=deadline)

    assert client.timeouts == [
        pytest.approx(20.0),
        pytest.approx(12.0),
        pytest.approx(4.0),
    ]
