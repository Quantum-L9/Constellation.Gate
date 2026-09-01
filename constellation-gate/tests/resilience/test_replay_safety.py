"""Retry requires BOTH an explicit safety contract AND a stable key."""

from __future__ import annotations

from typing import Any

import pytest
from constellation_node_sdk.transport.packet import create_transport_packet

from constellation_gate.resilience.replay_safety import (
    NEVER_REPLAY_SAFE_ACTIONS,
    ReplaySafetyError,
    ReplaySafetyPolicy,
)


def _packet(*, action: str, idempotency_key: str | None) -> Any:
    return create_transport_packet(
        action=action,
        payload={},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
        idempotency_key=idempotency_key,
    )


def test_default_policy_declares_nothing_replay_safe() -> None:
    policy = ReplaySafetyPolicy()
    assert policy.replay_safe_actions == frozenset()
    assert policy.may_replay(_packet(action="score", idempotency_key="k")) is False


def test_declared_safe_action_with_key_may_replay() -> None:
    policy = ReplaySafetyPolicy(["score"])
    assert policy.may_replay(_packet(action="score", idempotency_key="k")) is True
    assert policy.attempts_for(
        _packet(action="score", idempotency_key="k"), max_attempts=3
    ) == 3


def test_declared_safe_action_without_key_may_not_replay() -> None:
    """A safety contract with nothing to deduplicate on is not sufficient."""
    policy = ReplaySafetyPolicy(["score"])
    packet = _packet(action="score", idempotency_key=None)
    assert policy.may_replay(packet) is False
    assert policy.attempts_for(packet, max_attempts=3) == 1


def test_key_alone_does_not_enable_replay() -> None:
    """An idempotency key is necessary but NOT sufficient.

    A key lets a worker deduplicate; it is not evidence that the worker does.
    """
    policy = ReplaySafetyPolicy()  # "enrich" not declared safe
    packet = _packet(action="enrich", idempotency_key="k")
    assert policy.may_replay(packet) is False
    assert policy.attempts_for(packet, max_attempts=5) == 1


def test_converge_may_never_be_declared_replay_safe() -> None:
    """EIE owns converge retries; Gate must not stack a second waterfall."""
    assert "converge" in NEVER_REPLAY_SAFE_ACTIONS
    with pytest.raises(ReplaySafetyError):
        ReplaySafetyPolicy(["converge"])
    with pytest.raises(ReplaySafetyError):
        ReplaySafetyPolicy(["score", "CONVERGE"])


def test_converge_never_replays_even_with_a_key() -> None:
    policy = ReplaySafetyPolicy(["score"])
    packet = _packet(action="converge", idempotency_key="k")
    assert policy.is_declared_replay_safe("converge") is False
    assert policy.may_replay(packet) is False
    assert policy.attempts_for(packet, max_attempts=3) == 1


def test_action_matching_is_case_and_whitespace_insensitive() -> None:
    policy = ReplaySafetyPolicy(["  SCORE  "])
    assert policy.replay_safe_actions == frozenset({"score"})
    assert policy.may_replay(_packet(action="score", idempotency_key="k")) is True


def test_attempts_for_rejects_a_nonsense_budget() -> None:
    policy = ReplaySafetyPolicy(["score"])
    with pytest.raises(ValueError):
        policy.attempts_for(_packet(action="score", idempotency_key="k"), max_attempts=0)
