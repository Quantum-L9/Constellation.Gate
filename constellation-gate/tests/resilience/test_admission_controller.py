from __future__ import annotations

import pytest

from constellation_gate.resilience.admission_controller import AdmissionController
from constellation_gate.resilience.backpressure import BackpressurePolicy
from constellation_gate.resilience.load_shedding import LoadSheddingPolicy
from constellation_gate.resilience.rate_limiter import FixedWindowRateLimiter, RateLimitExceededError


def test_admission_controller_allows_when_under_all_limits() -> None:
    controller = AdmissionController(
        rate_limiter=FixedWindowRateLimiter(max_requests=10, window_seconds=60.0),
        load_shedding=LoadSheddingPolicy(max_in_flight=10),
        backpressure=BackpressurePolicy(max_queue_depth=10),
    )

    snapshot = controller.check(source_key="client-a", in_flight=1, queue_depth=1)

    assert snapshot.source_key == "client-a"
    assert snapshot.in_flight == 1
    assert snapshot.queue_depth == 1


def test_admission_controller_applies_rate_limit_first() -> None:
    controller = AdmissionController(
        rate_limiter=FixedWindowRateLimiter(max_requests=1, window_seconds=60.0),
        load_shedding=LoadSheddingPolicy(max_in_flight=10),
        backpressure=BackpressurePolicy(max_queue_depth=10),
    )

    controller.check(source_key="client-a", in_flight=0, queue_depth=0)

    with pytest.raises(RateLimitExceededError):
        controller.check(source_key="client-a", in_flight=0, queue_depth=0)
