"""ADR-GATE-008: the remaining packet budget reaches the actual worker transport.

`asyncio.wait_for` around the whole operation is NOT evidence that the network
attempt is bounded -- it only cancels the coroutine from outside while the socket
timeout may still be a fresh, full value. These tests assert the timeout handed
to the transport call itself.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from constellation_node_sdk.transport.packet import create_transport_packet
from constellation_node_sdk.transport.provenance import RoutingProvenance

from constellation_gate.resilience.deadline import Deadline, DeadlineExceeded
from constellation_gate.routing.dispatch import Dispatcher
from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry


class RecordingClient:
    def __init__(self, response_body: dict) -> None:
        self._response_body = response_body
        self.calls: list[dict] = []

    async def post(self, url: str, json: dict, headers: dict, timeout: float) -> httpx.Response:
        self.calls.append({"url": url, "timeout": timeout})
        return httpx.Response(
            status_code=200,
            json=self._response_body,
            request=httpx.Request("POST", url),
        )


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


def _response_body():
    return create_transport_packet(
        action="converge",
        payload={"ok": True},
        tenant="tenant-a",
        destination_node="gate",
        source_node="eie",
        reply_to="gate",
    ).model_dump_json_dict()


def test_worker_attempt_receives_remaining_budget_not_the_node_cap() -> None:
    clock = FakeClock()
    deadline = Deadline(30.0, clock=clock)
    client = RecordingClient(_response_body())
    dispatcher = Dispatcher(local_node="gate", registry=_registry(timeout_ms=25_000), client=client)

    # Most of the packet budget is already spent before dispatch begins.
    clock.advance(28.0)
    asyncio.run(dispatcher.dispatch(_inbound(), deadline=deadline))

    # The node cap is 25s; only 2s of the packet budget remain.
    assert client.calls[0]["timeout"] == pytest.approx(2.0)


def test_node_cap_still_bounds_a_generous_packet_budget() -> None:
    deadline = Deadline(600.0, clock=FakeClock())
    client = RecordingClient(_response_body())
    dispatcher = Dispatcher(local_node="gate", registry=_registry(timeout_ms=5_000), client=client)

    asyncio.run(dispatcher.dispatch(_inbound(), deadline=deadline))

    assert client.calls[0]["timeout"] == pytest.approx(5.0)


def test_expired_deadline_refuses_to_open_a_worker_connection() -> None:
    clock = FakeClock()
    deadline = Deadline(10.0, clock=clock)
    client = RecordingClient(_response_body())
    dispatcher = Dispatcher(local_node="gate", registry=_registry(timeout_ms=5_000), client=client)

    clock.advance(11.0)

    with pytest.raises(DeadlineExceeded):
        asyncio.run(dispatcher.dispatch(_inbound(), deadline=deadline))

    assert client.calls == []


def test_dispatch_without_a_deadline_falls_back_to_the_node_cap() -> None:
    client = RecordingClient(_response_body())
    dispatcher = Dispatcher(local_node="gate", registry=_registry(timeout_ms=15_000), client=client)

    asyncio.run(dispatcher.dispatch(_inbound()))

    assert client.calls[0]["timeout"] == pytest.approx(15.0)


def test_each_attempt_is_rebounded_rather_than_reset() -> None:
    """Two sequential attempts on one deadline must not each get a fresh cap."""
    clock = FakeClock()
    deadline = Deadline(30.0, clock=clock)
    client = RecordingClient(_response_body())
    dispatcher = Dispatcher(local_node="gate", registry=_registry(timeout_ms=25_000), client=client)

    asyncio.run(dispatcher.dispatch(_inbound(), deadline=deadline))
    clock.advance(20.0)
    asyncio.run(dispatcher.dispatch(_inbound(), deadline=deadline))

    first, second = client.calls[0]["timeout"], client.calls[1]["timeout"]
    assert first == pytest.approx(25.0)
    assert second == pytest.approx(10.0)
    assert second < first
