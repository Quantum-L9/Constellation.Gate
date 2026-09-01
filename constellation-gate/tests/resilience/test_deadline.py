"""The packet deadline is monotonic, single, and never refreshed."""

from __future__ import annotations

import asyncio

import pytest

from constellation_gate.resilience.deadline import (
    DeadlineExceededError,
    PacketDeadline,
    resolve_deadline,
)


class FakeClock:
    """Deterministic monotonic clock: tests assert budgets without sleeping."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_rejects_non_positive_budget() -> None:
    with pytest.raises(ValueError):
        PacketDeadline(0)
    with pytest.raises(ValueError):
        PacketDeadline(-1)


def test_remaining_decreases_and_never_refreshes() -> None:
    clock = FakeClock()
    deadline = PacketDeadline(10.0, clock=clock)

    assert deadline.remaining_seconds == pytest.approx(10.0)
    clock.advance(4.0)
    assert deadline.remaining_seconds == pytest.approx(6.0)
    clock.advance(4.0)
    assert deadline.remaining_seconds == pytest.approx(2.0)
    # Reading it repeatedly must not reset it.
    assert deadline.remaining_seconds == pytest.approx(2.0)


def test_remaining_floors_at_zero_and_reports_expired() -> None:
    clock = FakeClock()
    deadline = PacketDeadline(5.0, clock=clock)
    clock.advance(12.0)

    assert deadline.remaining_seconds == 0.0
    assert deadline.expired is True
    with pytest.raises(DeadlineExceededError):
        deadline.remaining_or_raise()


def test_budget_for_takes_the_smaller_of_remaining_and_node_cap() -> None:
    clock = FakeClock()
    deadline = PacketDeadline(30.0, clock=clock)

    # Node cap is the binding constraint early on.
    assert deadline.budget_for(10.0) == pytest.approx(10.0)

    # Once the packet has spent most of its budget, the packet binds instead --
    # this is the case that used to hand a worker a fresh full timeout.
    clock.advance(27.0)
    assert deadline.budget_for(10.0) == pytest.approx(3.0)


def test_budget_for_without_cap_is_the_remaining_budget() -> None:
    clock = FakeClock()
    deadline = PacketDeadline(8.0, clock=clock)
    clock.advance(3.0)
    assert deadline.budget_for(None) == pytest.approx(5.0)


def test_budget_for_raises_once_exhausted() -> None:
    clock = FakeClock()
    deadline = PacketDeadline(2.0, clock=clock)
    clock.advance(5.0)
    with pytest.raises(DeadlineExceededError):
        deadline.budget_for(30.0)


@pytest.mark.asyncio
async def test_sleep_consumes_the_same_budget() -> None:
    deadline = PacketDeadline(0.20)
    before = deadline.remaining_seconds
    await deadline.sleep(0.05)
    after = deadline.remaining_seconds
    assert after < before
    assert after == pytest.approx(before - 0.05, abs=0.05)


@pytest.mark.asyncio
async def test_sleep_past_the_deadline_raises_rather_than_overrunning() -> None:
    deadline = PacketDeadline(0.05)
    with pytest.raises(DeadlineExceededError):
        await deadline.sleep(5.0)


@pytest.mark.asyncio
async def test_deadline_exceeded_is_a_timeout_error() -> None:
    # Existing timeout-shaped handling must keep working.
    deadline = PacketDeadline(0.01)
    await asyncio.sleep(0.02)
    with pytest.raises(TimeoutError):
        deadline.remaining_or_raise()


def test_resolve_deadline_builds_from_packet_timeout() -> None:
    deadline = resolve_deadline(12.5)
    assert deadline.total_seconds == pytest.approx(12.5)
