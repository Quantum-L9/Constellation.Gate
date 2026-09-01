"""Gate does not replay a whole operation without proving it is safe to.

A worker timeout means "no answer arrived", never "no work happened". Retrying
because the exception was timeout-shaped is a correctness hazard: the worker may
have already applied the side effect Gate is about to ask for a second time.
"""

from __future__ import annotations

from typing import Any

import pytest
from constellation_node_sdk.transport.packet import TransportPacket, create_transport_packet

from constellation_gate.resilience.replay_safety import ReplaySafetyError, ReplaySafetyPolicy
from constellation_gate.services.execute_service import ExecuteService


class CountingTimeoutDispatcher:
    """Always times out; counts how many whole-operation attempts happened."""

    def __init__(self) -> None:
        self.attempts = 0

    async def dispatch(
        self,
        packet: TransportPacket,
        *,
        deadline: Any = None,
    ) -> TransportPacket:
        self.attempts += 1
        raise TimeoutError("worker did not answer")


class NoWorkflows:
    def has_workflow(self, action: str) -> bool:
        return False

    async def execute(self, packet: TransportPacket, *, deadline: Any = None) -> TransportPacket:
        raise AssertionError("no workflow should run")


class PassthroughValidator:
    def validate(self, body: dict[str, Any]) -> TransportPacket:
        return TransportPacket.model_validate(body)


def _service(dispatcher: Any) -> ExecuteService:
    return ExecuteService(
        local_node="gate",
        ingress_validator=PassthroughValidator(),
        dispatcher=dispatcher,
        workflow_engine=NoWorkflows(),
        registry=None,
    )


def _body(*, action: str, idempotency_key: str | None = None) -> dict[str, Any]:
    return create_transport_packet(
        action=action,
        payload={"a": 1},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
        idempotency_key=idempotency_key,
        timeout_ms=5_000,
    ).model_dump_json_dict()


@pytest.mark.asyncio
async def test_ordinary_action_runs_exactly_once_on_timeout() -> None:
    dispatcher = CountingTimeoutDispatcher()
    service = _service(dispatcher)

    with pytest.raises(TimeoutError):
        await service.execute(_body(action="score"))

    assert dispatcher.attempts == 1, (
        "a timeout-shaped exception must not, on its own, authorize a "
        "whole-operation replay"
    )


@pytest.mark.asyncio
async def test_idempotency_key_alone_does_not_enable_replay() -> None:
    dispatcher = CountingTimeoutDispatcher()
    service = _service(dispatcher)

    with pytest.raises(TimeoutError):
        await service.execute(_body(action="score", idempotency_key="k-1"))

    assert dispatcher.attempts == 1


@pytest.mark.asyncio
async def test_converge_is_never_retried_by_gate() -> None:
    """EIE owns provider retries for converge."""
    dispatcher = CountingTimeoutDispatcher()
    service = _service(dispatcher)

    with pytest.raises(TimeoutError):
        await service.execute(_body(action="converge", idempotency_key="k-1"))

    assert dispatcher.attempts == 1


@pytest.mark.asyncio
async def test_converge_cannot_be_opted_into_replay_by_configuration() -> None:
    with pytest.raises(ReplaySafetyError):
        ReplaySafetyPolicy(["converge"])


@pytest.mark.asyncio
async def test_declared_replay_safe_action_with_key_does_retry() -> None:
    """RetryPolicy is not deleted -- it is invoked only on a proven-safe path."""
    dispatcher = CountingTimeoutDispatcher()
    service = _service(dispatcher)
    service.replay_safety = ReplaySafetyPolicy(["score"])
    service.retry_policy.max_attempts = 3
    service.retry_policy.delay_seconds = 0.0

    with pytest.raises(TimeoutError):
        await service.execute(_body(action="score", idempotency_key="k-1"))

    assert dispatcher.attempts == 3


@pytest.mark.asyncio
async def test_declared_replay_safe_action_without_key_does_not_retry() -> None:
    dispatcher = CountingTimeoutDispatcher()
    service = _service(dispatcher)
    service.replay_safety = ReplaySafetyPolicy(["score"])
    service.retry_policy.max_attempts = 3
    service.retry_policy.delay_seconds = 0.0

    with pytest.raises(TimeoutError):
        await service.execute(_body(action="score"))

    assert dispatcher.attempts == 1


@pytest.mark.asyncio
async def test_retries_cannot_outlive_the_packet_deadline() -> None:
    """Retry sleeps are charged to the same budget, not granted fresh time."""
    dispatcher = CountingTimeoutDispatcher()
    service = _service(dispatcher)
    service.replay_safety = ReplaySafetyPolicy(["score"])
    service.retry_policy.max_attempts = 100
    service.retry_policy.delay_seconds = 0.05

    body = create_transport_packet(
        action="score",
        payload={},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
        idempotency_key="k-1",
        timeout_ms=150,  # 0.15s total budget
    ).model_dump_json_dict()

    with pytest.raises(TimeoutError):
        await service.execute(body)

    # Backoff consumes the budget, so the attempt count is bounded by the
    # deadline rather than running the full 100.
    assert 1 <= dispatcher.attempts < 100
