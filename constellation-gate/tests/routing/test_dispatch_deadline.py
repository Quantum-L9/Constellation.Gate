"""ADR-GATE-008 + INV-GATE-DOWNSTREAM-DEADLINE-IDENTITY.

``asyncio.wait_for`` around the whole operation is NOT evidence that the network
attempt is bounded -- it only cancels the coroutine from outside while the socket
timeout may still be a fresh, full value. These tests assert the budget that
actually reaches the wire.

They now assert something strictly stronger than "the socket timeout is right".
Gate writes the bounded remaining budget into the dispatch packet's
``header.timeout_ms``; Gate_SDK derives the socket deadline from that same field;
and the worker's runtime bounds its handler with it too. So the number Gate
waits, the number the socket enforces, and the number the worker is told are one
value, and each test below checks all three together. The earlier split -- a
child packet advertising the root's 30s while Gate waited 2s -- cannot recur
without failing here.
"""

from __future__ import annotations

import asyncio

import pytest
from constellation_node_sdk.transport.packet import create_transport_packet
from constellation_node_sdk.transport.provenance import RoutingProvenance
from support.sdk_worker import SdkWorker

from constellation_gate.resilience.deadline import Deadline, DeadlineExceeded
from constellation_gate.routing.dispatch import Dispatcher
from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _registry(*, timeout_ms: int) -> NodeRegistry:
    registry = NodeRegistry()
    registry.register_node(
        "eie",
        NodeRegistration(
            node_name="eie",
            internal_url="http://eie:8000",
            supported_actions=("converge",),
            timeout_ms=timeout_ms,
        ),
    )
    return registry


def _inbound(*, timeout_ms: int = 30_000):
    return create_transport_packet(
        action="converge",
        payload={"opaque": {"nested": [1, 2]}},
        tenant="tenant-a",
        destination_node="gate",
        source_node="odoo",
        reply_to="odoo",
        timeout_ms=timeout_ms,
        provenance=RoutingProvenance(
            origin_kind="node",
            requested_action="converge",
            resolved_by_gate=False,
            original_source_node="odoo",
        ),
    )


def _worker() -> SdkWorker:
    return SdkWorker(node_name="eie", action="converge")


async def _dispatch(worker: SdkWorker, registry: NodeRegistry, packet, deadline):
    async with worker.client() as client:
        dispatcher = Dispatcher(local_node="gate", registry=registry, client=client)
        return await dispatcher.dispatch(packet, deadline=deadline)


def _assert_one_budget(worker: SdkWorker, expected_seconds: float, *, index: int = 0) -> None:
    """The child header, the socket, and the worker's own budget must agree."""
    header_ms = worker.observed_timeout_ms[index]
    socket_seconds = worker.observed_socket_timeout[index]

    assert header_ms == pytest.approx(expected_seconds * 1000, abs=1), (
        "the packet the worker received advertises the wrong budget"
    )
    assert socket_seconds == pytest.approx(expected_seconds, abs=0.001), (
        "the deadline applied to the socket does not match the advertised budget"
    )
    assert socket_seconds == pytest.approx(header_ms / 1000, abs=0.001), (
        "INV-GATE-DOWNSTREAM-DEADLINE-IDENTITY: the socket deadline and the "
        "budget advertised to the worker have drifted apart"
    )


def test_worker_attempt_receives_remaining_budget_not_the_node_cap() -> None:
    clock = FakeClock()
    deadline = Deadline(30.0, clock=clock)
    worker = _worker()

    # Most of the packet budget is already spent before dispatch begins.
    clock.advance(28.0)
    asyncio.run(_dispatch(worker, _registry(timeout_ms=25_000), _inbound(), deadline))

    # The node cap is 25s; only 2s of the packet budget remain.
    _assert_one_budget(worker, 2.0)


def test_the_child_packet_does_not_inherit_the_root_budget() -> None:
    """The regression this closure exists to prevent, pinned explicitly."""
    clock = FakeClock()
    deadline = Deadline(30.0, clock=clock)
    worker = _worker()
    root = _inbound(timeout_ms=30_000)

    clock.advance(28.0)
    asyncio.run(_dispatch(worker, _registry(timeout_ms=25_000), root, deadline))

    assert worker.observed_timeout_ms[0] != root.header.timeout_ms, (
        "the worker was told the ROOT budget while Gate waited on the remaining "
        "one -- the exact deadline split this invariant forbids"
    )
    assert worker.observed_timeout_ms[0] < root.header.timeout_ms


def test_node_cap_still_bounds_a_generous_packet_budget() -> None:
    worker = _worker()
    deadline = Deadline(600.0, clock=FakeClock())
    asyncio.run(_dispatch(worker, _registry(timeout_ms=5_000), _inbound(), deadline))
    _assert_one_budget(worker, 5.0)


def test_expired_deadline_refuses_to_open_a_worker_connection() -> None:
    clock = FakeClock()
    deadline = Deadline(10.0, clock=clock)
    worker = _worker()

    registry = _registry(timeout_ms=5_000)
    packet = _inbound()
    clock.advance(11.0)

    with pytest.raises(DeadlineExceeded):
        asyncio.run(_dispatch(worker, registry, packet, deadline))

    assert worker.request_count == 0


def test_a_sub_millisecond_remainder_is_reported_as_a_deadline_failure() -> None:
    """A budget that rounds to 0ms must not reach the SDK as a malformed packet.

    The SDK rejects a non-positive budget as a CONFIGURATION error, which would
    read as "Gate is misconfigured" when what actually happened is "the operation
    ran out of time". Gate classifies it before it gets there.
    """
    clock = FakeClock()
    deadline = Deadline(10.0, clock=clock)
    worker = _worker()

    registry = _registry(timeout_ms=5_000)
    packet = _inbound()
    clock.advance(9.9999)

    with pytest.raises(DeadlineExceeded):
        asyncio.run(_dispatch(worker, registry, packet, deadline))

    assert worker.request_count == 0


def test_dispatch_without_a_deadline_falls_back_to_the_node_cap() -> None:
    worker = _worker()
    asyncio.run(_dispatch(worker, _registry(timeout_ms=15_000), _inbound(), None))
    _assert_one_budget(worker, 15.0)


def test_each_attempt_is_rebounded_rather_than_reset() -> None:
    """Two sequential attempts on one deadline must not each get a fresh cap."""
    clock = FakeClock()
    deadline = Deadline(30.0, clock=clock)
    worker = _worker()
    registry = _registry(timeout_ms=25_000)

    asyncio.run(_dispatch(worker, registry, _inbound(), deadline))
    clock.advance(20.0)
    asyncio.run(_dispatch(worker, registry, _inbound(), deadline))

    _assert_one_budget(worker, 25.0, index=0)
    _assert_one_budget(worker, 10.0, index=1)
    assert worker.observed_socket_timeout[1] < worker.observed_socket_timeout[0]
