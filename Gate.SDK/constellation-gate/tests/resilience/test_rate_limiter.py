from __future__ import annotations

import pytest

from constellation_gate.resilience.rate_limiter import (
    FixedWindowRateLimiter,
    RateLimitExceededError,
)


def test_rate_limiter_allows_up_to_limit_within_window() -> None:
    limiter = FixedWindowRateLimiter(max_requests=2, window_seconds=10.0)

    limiter.allow(key="client-a", now=100.0)
    limiter.allow(key="client-a", now=101.0)

    with pytest.raises(RateLimitExceededError):
        limiter.allow(key="client-a", now=101.5)


def test_rate_limiter_recovers_after_window_expires() -> None:
    limiter = FixedWindowRateLimiter(max_requests=2, window_seconds=10.0)

    limiter.allow(key="client-a", now=100.0)
    limiter.allow(key="client-a", now=101.0)
    limiter.allow(key="client-a", now=110.1)

    decision = limiter.decision_for(key="client-a", now=110.1)
    assert decision.allowed is True
    assert decision.retry_after_seconds == 0.0


def test_rate_limiter_isolated_by_key() -> None:
    limiter = FixedWindowRateLimiter(max_requests=1, window_seconds=10.0)

    limiter.allow(key="client-a", now=100.0)
    limiter.allow(key="client-b", now=100.0)

    with pytest.raises(RateLimitExceededError):
        limiter.allow(key="client-a", now=100.1)
