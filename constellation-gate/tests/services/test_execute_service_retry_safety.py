"""ADR-GATE-007 / ADR-GATE-008 at the ExecuteService boundary.

The regression these lock down: a generic wrapper that replayed EVERY action
three times on any TimeoutError, including canonical `converge`, whose provider
retry ownership belongs to EIE.
"""

from __future__ import annotations

import pytest
from constellation_node_sdk.transport.packet import TransportPacket, create_transport_packet

from constellation_gate.resilience.deadline import Deadline
from constellation_gate.resilience.replay_safety import REPLAY_SAFE_MAX_ATTEMPTS
from constellation_gate.services.execute_service import ExecuteService


class DummyValidator:
    def validate(self, body):
        return TransportPacket.model_validate(body)


class DummyWorkflow:
    def has_workflow(self, action):
        return False


class CountingTimeoutDispatcher:
    """Always times out; records how many whole-operation attempts Gate made."""

    def __init__(self) -> None:
        self.attempts = 0

    async def dispatch(self, packet):
        self.attempts += 1
        raise TimeoutError("worker timed out")


class DeadlineCapturingDispatcher:
    def __init__(self) -> None:
        self.deadlines: list[Deadline] = []

    async def dispatch(self, packet, *, deadline=None):
        self.deadlines.append(deadline)
        return packet


def _service(dispatcher, workflow=None) -> ExecuteService:
    return ExecuteService(
        local_node="gate",
        ingress_validator=DummyValidator(),
        dispatcher=dispatcher,
        workflow_engine=workflow or DummyWorkflow(),
        registry=None,
    )


def _packet(*, action: str, key: str | None = None, timeout_ms: int = 30_000):
    return create_transport_packet(
        action=action,
        payload={"opaque": 1},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
        idempotency_key=key,
        timeout_ms=timeout_ms,
    )


@pytest.mark.asyncio
async def test_converge_is_attempted_exactly_once_even_with_idempotency_key() -> None:
    dispatcher = CountingTimeoutDispatcher()
    service = _service(dispatcher)

    with pytest.raises(TimeoutError):
        await service.execute(_packet(action="converge", key="k1").model_dump_json_dict())

    assert dispatcher.attempts == 1


@pytest.mark.asyncio
async def test_arbitrary_action_is_not_silently_replayed_on_timeout() -> None:
    dispatcher = CountingTimeoutDispatcher()
    service = _service(dispatcher)

    with pytest.raises(TimeoutError):
        await service.execute(_packet(action="score", key="k1").model_dump_json_dict())

    assert dispatcher.attempts == 1


@pytest.mark.asyncio
async def test_declared_replay_safe_action_with_key_may_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "constellation_gate.resilience.replay_safety.GATE_REPLAY_SAFE_ACTIONS",
        frozenset({"probe"}),
    )
    dispatcher = CountingTimeoutDispatcher()
    service = _service(dispatcher)
    service.retry_policy.delay_seconds = 0.0

    with pytest.raises(TimeoutError):
        await service.execute(_packet(action="probe", key="k1").model_dump_json_dict())

    assert dispatcher.attempts == REPLAY_SAFE_MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_declared_replay_safe_action_without_key_is_not_replayed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "constellation_gate.resilience.replay_safety.GATE_REPLAY_SAFE_ACTIONS",
        frozenset({"probe"}),
    )
    dispatcher = CountingTimeoutDispatcher()
    service = _service(dispatcher)
    service.retry_policy.delay_seconds = 0.0

    with pytest.raises(TimeoutError):
        await service.execute(_packet(action="probe").model_dump_json_dict())

    assert dispatcher.attempts == 1


@pytest.mark.asyncio
async def test_operator_ceiling_can_narrow_but_never_widen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "constellation_gate.resilience.replay_safety.GATE_REPLAY_SAFE_ACTIONS",
        frozenset({"probe"}),
    )

    narrowed = CountingTimeoutDispatcher()
    service = _service(narrowed)
    service.retry_policy.max_attempts = 1
    with pytest.raises(TimeoutError):
        await service.execute(_packet(action="probe", key="k").model_dump_json_dict())
    assert narrowed.attempts == 1

    # Raising the ceiling cannot widen a non-replay-safe action's budget.
    widened = CountingTimeoutDispatcher()
    service2 = _service(widened)
    service2.retry_policy.max_attempts = 10
    service2.retry_policy.delay_seconds = 0.0
    with pytest.raises(TimeoutError):
        await service2.execute(_packet(action="converge", key="k").model_dump_json_dict())
    assert widened.attempts == 1


@pytest.mark.asyncio
async def test_execution_receives_one_shared_monotonic_deadline() -> None:
    dispatcher = DeadlineCapturingDispatcher()
    service = _service(dispatcher)

    await service.execute(_packet(action="score", timeout_ms=4_000).model_dump_json_dict())

    assert len(dispatcher.deadlines) == 1
    deadline = dispatcher.deadlines[0]
    assert isinstance(deadline, Deadline)
    assert deadline.total_seconds == pytest.approx(4.0)


@pytest.mark.asyncio
async def test_retry_sleep_does_not_outlive_the_packet_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retry must not sleep past the deadline to start an attempt that cannot finish."""
    monkeypatch.setattr(
        "constellation_gate.resilience.replay_safety.GATE_REPLAY_SAFE_ACTIONS",
        frozenset({"probe"}),
    )
    dispatcher = CountingTimeoutDispatcher()
    service = _service(dispatcher)
    # Backoff far exceeds the 50ms packet budget -> no second attempt.
    service.retry_policy.delay_seconds = 5.0

    with pytest.raises(TimeoutError):
        await service.execute(
            _packet(action="probe", key="k", timeout_ms=50).model_dump_json_dict()
        )

    assert dispatcher.attempts == 1
