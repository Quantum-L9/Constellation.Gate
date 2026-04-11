from __future__ import annotations

import pytest

from constellation_gate.orchestration.condition_eval import SafeConditionEvaluator


def test_condition_eval_supports_boolean_and_subscript_access() -> None:
    evaluator = SafeConditionEvaluator()

    result = evaluator.evaluate(
        "payload['score'] >= 70 and accumulated['enabled'] == True",
        payload={"score": 88},
        response=None,
        action="score",
        accumulated={"enabled": True},
    )

    assert result is True


def test_condition_eval_supports_response_and_membership() -> None:
    evaluator = SafeConditionEvaluator()

    result = evaluator.evaluate(
        "'completed' in response['status']",
        payload={},
        response={"status": "completed"},
        action="score",
        accumulated={},
    )

    assert result is True


def test_condition_eval_rejects_calls() -> None:
    evaluator = SafeConditionEvaluator()

    with pytest.raises(ValueError):
        evaluator.evaluate(
            "len(payload) > 0",
            payload={"x": 1},
            response=None,
            action="score",
            accumulated={},
        )
