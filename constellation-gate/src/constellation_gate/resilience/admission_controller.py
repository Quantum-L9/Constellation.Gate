from __future__ import annotations

from dataclasses import dataclass

from constellation_gate.resilience.backpressure import BackpressurePolicy
from constellation_gate.resilience.load_shedding import LoadSheddingPolicy
from constellation_gate.resilience.rate_limiter import FixedWindowRateLimiter


@dataclass(frozen=True)
class AdmissionSnapshot:
    source_key: str
    in_flight: int
    queue_depth: int


class AdmissionController:
    """
    Gate ingress admission controller.

    Order is deterministic:
    1. rate limit by source
    2. load shedding by in-flight count
    3. backpressure by queue depth
    """

    def __init__(
        self,
        *,
        rate_limiter: FixedWindowRateLimiter,
        load_shedding: LoadSheddingPolicy,
        backpressure: BackpressurePolicy,
    ) -> None:
        self._rate_limiter = rate_limiter
        self._load_shedding = load_shedding
        self._backpressure = backpressure

    def check(self, *, source_key: str, in_flight: int, queue_depth: int) -> AdmissionSnapshot:
        self._rate_limiter.allow(key=source_key)
        self._load_shedding.enforce(in_flight=in_flight)
        self._backpressure.enforce(queue_depth=queue_depth)
        return AdmissionSnapshot(
            source_key=source_key,
            in_flight=in_flight,
            queue_depth=queue_depth,
        )
