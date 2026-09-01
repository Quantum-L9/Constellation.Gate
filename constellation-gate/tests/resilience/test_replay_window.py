"""The replay window is real, enforced on the hot path, and bounded."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from constellation_gate.resilience.replay_guard import ReplayDetectedError, ReplayGuard


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def test_first_occurrence_is_accepted() -> None:
    guard = ReplayGuard(window_seconds=300)
    guard.check_and_record("packet-1")
    assert guard.size() == 1


def test_duplicate_inside_the_window_is_rejected() -> None:
    clock = FakeClock()
    guard = ReplayGuard(window_seconds=300, clock=clock)

    guard.check_and_record("packet-1")
    clock.advance(299)
    with pytest.raises(ReplayDetectedError):
        guard.check_and_record("packet-1")


def test_same_packet_id_after_the_window_is_accepted_again() -> None:
    """The advertised window must actually expire.

    Previously expiry depended on someone calling prune(); nothing did, so a
    packet_id was rejected forever and the window was decorative.
    """
    clock = FakeClock()
    guard = ReplayGuard(window_seconds=300, clock=clock)

    guard.check_and_record("packet-1")
    clock.advance(301)
    guard.check_and_record("packet-1")  # must not raise


def test_expiry_happens_on_the_hot_path_without_manual_prune() -> None:
    clock = FakeClock()
    guard = ReplayGuard(window_seconds=60, clock=clock)

    for i in range(50):
        guard.check_and_record(f"packet-{i}")
    assert guard.size() == 50

    clock.advance(61)
    # A single ordinary call must retire the aged entries.
    guard.check_and_record("packet-new")
    assert guard.size() == 1


def test_state_is_bounded_under_sustained_unique_load() -> None:
    """A burst of unique packets inside the window cannot exhaust memory."""
    guard = ReplayGuard(window_seconds=3600, max_entries=100)

    for i in range(1000):
        guard.check_and_record(f"packet-{i}")

    assert guard.size() <= 100


def test_ceiling_evicts_oldest_first() -> None:
    guard = ReplayGuard(window_seconds=3600, max_entries=3)
    for i in range(5):
        guard.check_and_record(f"packet-{i}")

    # packet-0/1 were evicted, so they are accepted again; packet-4 is still held.
    guard.check_and_record("packet-0")
    with pytest.raises(ReplayDetectedError):
        guard.check_and_record("packet-4")


def test_prune_remains_available_but_correctness_no_longer_depends_on_it() -> None:
    clock = FakeClock()
    guard = ReplayGuard(window_seconds=10, clock=clock)
    guard.check_and_record("packet-1")
    clock.advance(11)
    guard.prune()
    assert guard.size() == 0


def test_replay_detected_error_is_a_value_error() -> None:
    # Existing handlers catch ValueError; the typed error must stay compatible.
    guard = ReplayGuard()
    guard.check_and_record("packet-1")
    with pytest.raises(ValueError):
        guard.check_and_record("packet-1")


def test_rejects_nonsense_configuration() -> None:
    with pytest.raises(ValueError):
        ReplayGuard(window_seconds=0)
    with pytest.raises(ValueError):
        ReplayGuard(max_entries=0)
