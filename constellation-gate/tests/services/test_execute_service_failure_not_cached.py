"""SEAM-013: a failed attempt must not be cached under the idempotency key.

Gate caches the answer to an idempotency-keyed operation so a duplicate delivery
is answered without re-executing the worker. That is only safe for a terminal
success. Caching a worker `failure` packet -- or a response whose response hop
reports `failed` -- would answer every later retry of the same logical operation
with the stale failure, defeating the retry the key exists to make safe.
"""

from __future__ import annotations

import pytest
from constellation_node_sdk.runtime.execution import (
    create_error_transport_packet,
    execute_transport_packet,
)
from constellation_node_sdk.runtime.handlers import clear_handlers, register_handler
from constellation_node_sdk.transport.packet import TransportPacket, create_transport_packet

from constellation_gate.services.execute_service import ExecuteService, _is_terminal_success


class _Validator:
    def validate(self, body):
        return TransportPacket.model_validate(body)


class _NoWorkflow:
    def has_workflow(self, action):
        return False


class _ScriptedDispatcher:
    """First call fails at the worker, second call succeeds."""

    def __init__(self) -> None:
        self.calls = 0

    async def dispatch(self, packet):
        self.calls += 1
        if self.calls == 1:
            return create_error_transport_packet(
                packet, RuntimeError("worker exploded"), node_name="worker"
            )
        return packet


def _packet(key: str | None = "op-1") -> dict:
    return create_transport_packet(
        action="score",
        payload={"x": 1},
        tenant="t",
        destination_node="gate",
        source_node="client",
        reply_to="client",
        idempotency_key=key,
    ).model_dump_json_dict()


@pytest.fixture(autouse=True)
def _clean_handlers():
    clear_handlers()
    yield
    clear_handlers()


@pytest.mark.asyncio
async def test_failure_packet_is_not_cached_so_a_retry_re_executes() -> None:
    dispatcher = _ScriptedDispatcher()
    service = ExecuteService(
        local_node="gate",
        ingress_validator=_Validator(),
        dispatcher=dispatcher,
        workflow_engine=_NoWorkflow(),
        registry=None,
    )

    first = await service.execute(_packet())
    assert first.header.packet_type == "failure"
    assert len(service.idempotency_store) == 0

    second = await service.execute(_packet())
    assert dispatcher.calls == 2, "the retry must reach the worker, not the cache"
    assert second.header.packet_type != "failure"
    assert len(service.idempotency_store) == 1


def test_response_hop_marked_failed_is_not_terminal_success() -> None:
    """A `response` packet whose response hop reports `failed` is not cacheable."""
    from constellation_node_sdk.transport.hop_trace import make_response_hop

    inbound = create_transport_packet(
        action="score",
        payload={"x": 1},
        tenant="t",
        destination_node="worker",
        source_node="gate",
        reply_to="gate",
    )
    answer = inbound.derive(
        packet_type="response",
        source_node="worker",
        destination_node="gate",
        reply_to="worker",
        payload={"state": "failed"},
    )
    answer = answer.with_hop(
        make_response_hop(
            packet=answer,
            node="worker",
            action="score",
            status="failed",
            error_code="handler_failed",
        )
    )
    assert answer.header.packet_type == "response"
    assert _is_terminal_success(answer) is False


@pytest.mark.asyncio
async def test_handler_declared_failure_becomes_a_failure_packet() -> None:
    """SDK runtime: a handler answering status=failed yields a `failure` packet."""
    register_handler("score", lambda _t, _p: {"status": "failed", "reason": "no"})
    inbound = create_transport_packet(
        action="score",
        payload={"x": 1},
        tenant="t",
        destination_node="worker",
        source_node="gate",
        reply_to="gate",
    )
    try:
        answer = await execute_transport_packet(inbound, node_name="worker", dev_mode=True)
    except Exception as exc:  # the runtime app converts this into a failure packet
        answer = create_error_transport_packet(inbound, exc, node_name="worker")
    assert _is_terminal_success(answer) is False


@pytest.mark.asyncio
async def test_successful_response_is_terminal_success() -> None:
    register_handler("score", lambda _t, _p: {"status": "completed", "score": 1})
    inbound = create_transport_packet(
        action="score",
        payload={"x": 1},
        tenant="t",
        destination_node="worker",
        source_node="gate",
        reply_to="gate",
    )
    answer = await execute_transport_packet(inbound, node_name="worker", dev_mode=True)
    assert _is_terminal_success(answer) is True
