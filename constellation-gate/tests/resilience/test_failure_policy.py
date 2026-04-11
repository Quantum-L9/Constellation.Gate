from __future__ import annotations

from constellation_gate.resilience.failure_policy import FailurePolicy


def test_failure_policy_classifies_and_retries() -> None:
    policy = FailurePolicy()
    assert policy.classify(TimeoutError()) == "timeout"
    assert policy.should_retry("timeout") is True
    assert policy.should_retry("validation") is False
