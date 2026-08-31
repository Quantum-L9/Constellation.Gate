"""ADR-GATE-008: one monotonic packet deadline governs Gate execution."""

from __future__ import annotations

import pytest
from constellation_node_sdk.transport.packet import create_transport_packet

from constellation_gate.resilience.deadline import (
    Deadline,
    DeadlineExceeded,
    deadline_for_packet,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_remaining_budget_decreases_as_time_is_spent() -> None:
    clock = FakeClock()
    deadline = Deadline(10.0, clock=clock)

    assert deadline.remaining_seconds() == pytest.approx(10.0)
    clock.advance(4.0)
    assert deadline.remaining_seconds() == pytest.approx(6.0)


def test_remaining_budget_never_goes_negative() -> None:
    clock = FakeClock()
    deadline = Deadline(1.0, clock=clock)
    clock.advance(50.0)

    assert deadline.remaining_seconds() == 0.0
    assert deadline.expired() is True


def test_downstream_attempt_gets_remaining_budget_not_a_fresh_timeout() -> None:
    """The core invariant: a later attempt is bounded by what is left."""
    clock = FakeClock()
    deadline = Deadline(30.0, clock=clock)

    # A node configured with a 25s cap on a fresh packet gets its cap.
    assert deadline.bounded_by(25.0) == pytest.approx(25.0)

    # After 28s of the packet budget is spent, the SAME node cap must not
    # hand out another 25s -- only the 2s that remain.
    clock.advance(28.0)
    assert deadline.bounded_by(25.0) == pytest.approx(2.0)


def test_node_cap_bounds_a_generous_packet_budget() -> None:
    deadline = Deadline(600.0, clock=FakeClock())
    assert deadline.bounded_by(5.0) == pytest.approx(5.0)


def test_bounded_by_without_cap_returns_remaining() -> None:
    clock = FakeClock()
    deadline = Deadline(10.0, clock=clock)
    clock.advance(3.0)
    assert deadline.bounded_by(None) == pytest.approx(7.0)


def test_raise_if_expired_reports_the_stage() -> None:
    clock = FakeClock()
    deadline = Deadline(1.0, clock=clock)
    deadline.raise_if_expired(stage="worker dispatch")

    clock.advance(2.0)
    with pytest.raises(DeadlineExceeded, match="worker dispatch"):
        deadline.raise_if_expired(stage="worker dispatch")


def test_deadline_exceeded_is_a_timeout_error() -> None:
    """Existing timeout handling keeps working, while staying distinguishable."""
    assert issubclass(DeadlineExceeded, TimeoutError)


def test_deadline_derives_from_the_packet_budget() -> None:
    packet = create_transport_packet(
        action="converge",
        payload={},
        tenant="t",
        destination_node="gate",
        source_node="client",
        reply_to="client",
        timeout_ms=4_500,
    )
    deadline = deadline_for_packet(packet, clock=FakeClock())
    assert deadline.total_seconds == pytest.approx(4.5)


def test_zero_or_negative_budget_is_rejected() -> None:
    with pytest.raises(ValueError):
        Deadline(0.0)
    with pytest.raises(ValueError):
        Deadline(-1.0)


def test_deadline_uses_a_monotonic_source_by_default() -> None:
    """A wall-clock jump must not extend or truncate a packet budget."""
    import time as _time

    assert Deadline(1.0)._clock is _time.monotonic
