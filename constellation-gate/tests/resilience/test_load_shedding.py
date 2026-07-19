from __future__ import annotations

import pytest

from constellation_gate.resilience.load_shedding import LoadSheddingPolicy, LoadShedError


def test_load_shedding_allows_below_threshold() -> None:
    policy = LoadSheddingPolicy(max_in_flight=3)

    decision = policy.decision_for(in_flight=2)

    assert decision.allowed is True
    assert decision.reason is None


def test_load_shedding_rejects_at_threshold() -> None:
    policy = LoadSheddingPolicy(max_in_flight=3)

    decision = policy.decision_for(in_flight=3)

    assert decision.allowed is False
    assert decision.reason == "in_flight_limit_exceeded"


def test_load_shedding_enforce_raises() -> None:
    policy = LoadSheddingPolicy(max_in_flight=1)

    with pytest.raises(LoadShedError):
        policy.enforce(in_flight=1)
