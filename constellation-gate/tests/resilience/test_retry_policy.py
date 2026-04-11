from __future__ import annotations

import pytest

from constellation_gate.resilience.retry_policy import RetryPolicy


@pytest.mark.asyncio
async def test_retry_policy_retries_timeout_and_then_succeeds() -> None:
    policy = RetryPolicy(max_attempts=2, delay_seconds=0.0)

    state = {"calls": 0}

    async def flaky():
        state["calls"] += 1
        if state["calls"] == 1:
            raise TimeoutError("temporary")
        return "ok"

    result = await policy.run(flaky)

    assert result == "ok"
    assert state["calls"] == 2


@pytest.mark.asyncio
async def test_retry_policy_does_not_retry_non_retryable_exception() -> None:
    policy = RetryPolicy(max_attempts=3, delay_seconds=0.0)

    async def fail():
        raise ValueError("bad input")

    with pytest.raises(ValueError, match="bad input"):
        await policy.run(fail)


def test_retry_policy_decision_respects_attempt_budget() -> None:
    policy = RetryPolicy(max_attempts=2, delay_seconds=0.25, backoff_multiplier=2.0)

    first = policy.decision_for(attempt=1, exc=TimeoutError("x"))
    second = policy.decision_for(attempt=2, exc=TimeoutError("x"))

    assert first.should_retry is True
    assert first.delay_seconds == 0.25
    assert second.should_retry is False
    assert second.delay_seconds == 0.0
