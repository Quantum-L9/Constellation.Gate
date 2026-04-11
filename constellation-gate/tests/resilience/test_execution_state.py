from __future__ import annotations

from constellation_gate.resilience.execution_state import ExecutionState


def test_execution_state_defaults_and_fields() -> None:
    state = ExecutionState(
        packet_id="packet-1",
        status="pending",
    )

    assert state.packet_id == "packet-1"
    assert state.status == "pending"
    assert state.attempts == 0


def test_execution_state_tracks_attempt_updates() -> None:
    state = ExecutionState(
        packet_id="packet-2",
        status="running",
        attempts=1,
    )

    assert state.packet_id == "packet-2"
    assert state.status == "running"
    assert state.attempts == 1
