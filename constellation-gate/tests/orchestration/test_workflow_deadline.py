"""A workflow shares the packet's one budget; it does not buy a fresh one per step.

ExecuteService probes a collaborator's signature and only passes the deadline to
one that declares it. An engine without the parameter therefore ran its steps
with NO deadline at all -- an N-step workflow could consume N x the per-node
timeout inside a packet budget that claimed one. These tests pin both halves:
the engine accepts the budget, and it passes the same object down.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest
from constellation_node_sdk.transport.packet import TransportPacket, create_transport_packet

from constellation_gate.orchestration.workflow_engine import WorkflowEngine
from constellation_gate.orchestration.workflow_models import WorkflowDefinition
from constellation_gate.resilience.deadline import Deadline, DeadlineExceeded


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class RecordingDispatcher:
    """Records the deadline object and the timeout each step was given."""

    def __init__(self) -> None:
        self.deadlines: list[Any] = []
        self.step_timeouts: list[int | None] = []

    async def dispatch(
        self,
        packet: TransportPacket,
        *,
        deadline: Any = None,
    ) -> TransportPacket:
        self.deadlines.append(deadline)
        self.step_timeouts.append(packet.header.timeout_ms)
        return packet.derive(
            packet_type="response",
            source_node="worker",
            destination_node="gate",
            reply_to="worker",
            payload={"ok": True},
        )


def _engine(dispatcher: Any, *, step_timeout_ms: int | None = None) -> WorkflowEngine:
    definition = WorkflowDefinition.model_validate(
        {
            "name": "pipeline",
            "steps": [
                {"name": "one", "action": "score", "timeout_ms": step_timeout_ms},
                {"name": "two", "action": "enrich", "timeout_ms": step_timeout_ms},
            ],
        }
    )
    return WorkflowEngine({"pipeline": definition}, dispatcher, local_node="gate")


def _packet(*, timeout_ms: int = 30_000) -> TransportPacket:
    return create_transport_packet(
        action="pipeline",
        payload={"a": 1},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
        timeout_ms=timeout_ms,
    )


def test_execute_declares_the_deadline_parameter() -> None:
    """The signature probe in ExecuteService depends on this being declared.

    If this regresses, the engine silently loses its budget rather than failing.
    """
    signature = inspect.signature(WorkflowEngine.execute)
    assert "deadline" in signature.parameters
    assert signature.parameters["deadline"].kind is inspect.Parameter.KEYWORD_ONLY


@pytest.mark.asyncio
async def test_every_step_receives_the_same_deadline_object() -> None:
    dispatcher = RecordingDispatcher()
    deadline = Deadline(30.0, clock=FakeClock())

    await _engine(dispatcher).execute(_packet(), deadline=deadline)

    assert len(dispatcher.deadlines) == 2
    assert all(d is deadline for d in dispatcher.deadlines), (
        "steps must share one budget, not each receive a fresh one"
    )


@pytest.mark.asyncio
async def test_step_timeout_is_clamped_to_the_remaining_budget() -> None:
    """A generous per-step timeout may not outlive the packet."""
    clock = FakeClock()
    dispatcher = RecordingDispatcher()
    deadline = Deadline(30.0, clock=clock)

    clock.advance(28.0)  # only 2s left
    await _engine(dispatcher, step_timeout_ms=25_000).execute(_packet(), deadline=deadline)

    assert dispatcher.step_timeouts[0] is not None
    assert dispatcher.step_timeouts[0] <= 2_000, (
        f"step declared 25s but only 2s remained; got {dispatcher.step_timeouts[0]}ms"
    )


@pytest.mark.asyncio
async def test_workflow_refuses_to_start_a_step_on_an_exhausted_budget() -> None:
    clock = FakeClock()
    dispatcher = RecordingDispatcher()
    deadline = Deadline(10.0, clock=clock)

    clock.advance(11.0)
    with pytest.raises(DeadlineExceeded):
        await _engine(dispatcher).execute(_packet(), deadline=deadline)

    assert dispatcher.deadlines == [], "no step may be dispatched past the deadline"


@pytest.mark.asyncio
async def test_workflow_without_a_deadline_still_runs() -> None:
    """Direct unit-level use (no deadline) keeps the declared step timeout."""
    dispatcher = RecordingDispatcher()
    await _engine(dispatcher, step_timeout_ms=5_000).execute(_packet())

    assert dispatcher.deadlines == [None, None]
    assert dispatcher.step_timeouts == [5_000, 5_000]
