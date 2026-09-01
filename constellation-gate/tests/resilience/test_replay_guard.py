from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from constellation_gate.resilience.replay_guard import ReplayGuard


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def test_replay_guard_blocks_duplicate_packet() -> None:
    guard = ReplayGuard()
    guard.check_and_record("p1")
    with pytest.raises(ValueError):
        guard.check_and_record("p1")


def test_duplicate_inside_the_window_is_rejected() -> None:
    clock = FakeClock()
    guard = ReplayGuard(window_seconds=300, clock=clock)

    guard.check_and_record("p1")
    clock.advance(299)

    with pytest.raises(ValueError, match="replay detected"):
        guard.check_and_record("p1")


def test_same_packet_id_after_the_window_is_accepted() -> None:
    """The declared window is the behaviour, enforced on the hot path."""
    clock = FakeClock()
    guard = ReplayGuard(window_seconds=300, clock=clock)

    guard.check_and_record("p1")
    clock.advance(301)

    guard.check_and_record("p1")  # must not raise


def test_expiry_happens_inside_check_and_record_without_calling_prune() -> None:
    """State must not depend on an operator remembering to prune()."""
    clock = FakeClock()
    guard = ReplayGuard(window_seconds=60, clock=clock)

    for index in range(50):
        guard.check_and_record(f"p{index}")
    assert len(guard) == 50

    # Every recorded id ages out; a single subsequent check must collect them.
    clock.advance(61)
    guard.check_and_record("fresh")

    assert len(guard) == 1


def test_replay_state_stays_bounded_under_sustained_load() -> None:
    """Seen-state is bounded by arrival rate * window, not by process uptime."""
    clock = FakeClock()
    guard = ReplayGuard(window_seconds=10, clock=clock)

    for index in range(500):
        guard.check_and_record(f"packet-{index}")
        clock.advance(1)

    # 500 packets over 500 simulated seconds, 10s window -> ~11 retained, not 500.
    assert len(guard) <= 12


def test_prune_remains_available_for_operators() -> None:
    clock = FakeClock()
    guard = ReplayGuard(window_seconds=5, clock=clock)
    guard.check_and_record("p1")

    clock.advance(6)
    guard.prune()

    assert len(guard) == 0


def test_window_must_be_positive() -> None:
    with pytest.raises(ValueError):
        ReplayGuard(window_seconds=0)
