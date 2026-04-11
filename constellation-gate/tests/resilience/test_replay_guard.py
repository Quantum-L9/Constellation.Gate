from __future__ import annotations

import pytest

from constellation_gate.resilience.replay_guard import ReplayGuard


def test_replay_guard_blocks_duplicate_packet() -> None:
    guard = ReplayGuard()
    guard.check_and_record("p1")
    with pytest.raises(ValueError):
        guard.check_and_record("p1")
