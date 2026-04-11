from __future__ import annotations

import pytest

from constellation_gate.resilience.backpressure import (
    BackpressureExceededError,
    BackpressurePolicy,
)


def test_backpressure_allows_below_queue_limit() -> None:
    policy = BackpressurePolicy(max_queue_depth=5)

    decision = policy.decision_for(queue_depth=4)

    assert decision.allowed is True
    assert decision.reason is None


def test_backpressure_rejects_at_queue_limit() -> None:
    policy = BackpressurePolicy(max_queue_depth=5)

    decision = policy.decision_for(queue_depth=5)

    assert decision.allowed is False
    assert decision.reason == "queue_depth_limit_exceeded"


def test_backpressure_enforce_raises() -> None:
    policy = BackpressurePolicy(max_queue_depth=2)

    with pytest.raises(BackpressureExceededError):
        policy.enforce(queue_depth=2)
