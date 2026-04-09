from __future__ import annotations

from dataclasses import dataclass


class LoadShedError(RuntimeError):
    """Raised when Gate rejects new work under configured pressure limits."""


@dataclass(frozen=True)
class LoadSheddingDecision:
    allowed: bool
    reason: str | None = None


class LoadSheddingPolicy:
    """
    Simple deterministic admission guard based on in-flight requests.

    This is intentionally narrow: it provides a stable contract now and can be
    expanded later with queue depth, latency, or memory pressure inputs.
    """

    def __init__(self, *, max_in_flight: int) -> None:
        if max_in_flight < 1:
            raise ValueError("max_in_flight must be >= 1")
        self._max_in_flight = max_in_flight

    @property
    def max_in_flight(self) -> int:
        return self._max_in_flight

    def decision_for(self, *, in_flight: int) -> LoadSheddingDecision:
        if in_flight < 0:
            raise ValueError("in_flight must be >= 0")
        if in_flight >= self._max_in_flight:
            return LoadSheddingDecision(allowed=False, reason="in_flight_limit_exceeded")
        return LoadSheddingDecision(allowed=True, reason=None)

    def enforce(self, *, in_flight: int) -> None:
        decision = self.decision_for(in_flight=in_flight)
        if not decision.allowed:
            raise LoadShedError(decision.reason or "load_shed")
