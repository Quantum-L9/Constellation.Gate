"""ADR-GATE-007: whole-operation replay requires idempotency AND explicit safety."""

from __future__ import annotations

import pytest

from constellation_gate.resilience.replay_safety import (
    DEFAULT_MAX_ATTEMPTS,
    GATE_REPLAY_SAFE_ACTIONS,
    REPLAY_SAFE_MAX_ATTEMPTS,
    WORKER_OWNED_RETRY_ACTIONS,
    is_declared_replay_safe,
    max_attempts_for,
)


def test_default_attempt_budget_is_a_single_attempt() -> None:
    assert DEFAULT_MAX_ATTEMPTS == 1


@pytest.mark.parametrize("action", sorted(WORKER_OWNED_RETRY_ACTIONS))
def test_worker_owned_actions_are_never_gate_replay_safe(action: str) -> None:
    """Provider retry ownership belongs to the worker (ADR-GATE-016)."""
    assert not is_declared_replay_safe(action)
    assert max_attempts_for(action=action, has_idempotency_key=True) == 1
    assert max_attempts_for(action=action, has_idempotency_key=False) == 1


def test_converge_gets_exactly_one_gate_attempt() -> None:
    """The canonical enrichment rail must not be multiplied by Gate."""
    assert max_attempts_for(action="converge", has_idempotency_key=True) == 1


def test_unknown_action_fails_closed_to_one_attempt() -> None:
    assert max_attempts_for(action="some-unregistered-action", has_idempotency_key=True) == 1


def test_idempotency_key_alone_does_not_enable_replay() -> None:
    """A key makes a replay recognisable, not harmless."""
    assert max_attempts_for(action="anything", has_idempotency_key=True) == DEFAULT_MAX_ATTEMPTS


def test_declared_replay_safe_action_still_requires_an_idempotency_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "constellation_gate.resilience.replay_safety.GATE_REPLAY_SAFE_ACTIONS",
        frozenset({"probe"}),
    )

    assert max_attempts_for(action="probe", has_idempotency_key=False) == DEFAULT_MAX_ATTEMPTS
    assert max_attempts_for(action="probe", has_idempotency_key=True) == REPLAY_SAFE_MAX_ATTEMPTS


def test_replay_safe_set_is_empty_by_default() -> None:
    """Nothing is replay-safe until a contract says so, backed by a test."""
    assert GATE_REPLAY_SAFE_ACTIONS == frozenset()


def test_replay_safe_and_worker_owned_sets_are_disjoint() -> None:
    assert GATE_REPLAY_SAFE_ACTIONS & WORKER_OWNED_RETRY_ACTIONS == frozenset()


def test_action_normalization_cannot_smuggle_a_replay_safe_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "constellation_gate.resilience.replay_safety.GATE_REPLAY_SAFE_ACTIONS",
        frozenset({"probe"}),
    )

    assert is_declared_replay_safe("  PROBE  ")
    assert not is_declared_replay_safe("probe-extra")
