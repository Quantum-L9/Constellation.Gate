from __future__ import annotations

from constellation_gate.resilience import (
    BackpressurePolicy,
    CircuitBreaker,
    DeadLetterQueue,
    FixedWindowRateLimiter,
    LoadSheddingPolicy,
    ReplayGuard,
    RetryPolicy,
    TimeoutPolicy,
)


def test_resilience_package_exports_core_admission_and_failure_types() -> None:
    assert FixedWindowRateLimiter(max_requests=10, window_seconds=1.0).max_requests == 10
    assert CircuitBreaker(failure_threshold=2, recovery_timeout_seconds=5.0).snapshot.state == "closed"
    assert LoadSheddingPolicy(max_in_flight=5).max_in_flight == 5
    assert BackpressurePolicy(max_queue_depth=5).max_queue_depth == 5
    assert DeadLetterQueue().size() == 0
    assert isinstance(ReplayGuard(window_seconds=5), ReplayGuard)
    assert isinstance(RetryPolicy(), RetryPolicy)
    assert isinstance(TimeoutPolicy(), TimeoutPolicy)
