from __future__ import annotations

import pytest

from constellation_gate.schemas.workflow import (
    WorkflowConfigSchema,
    WorkflowSchema,
    WorkflowStepSchema,
)


def test_workflow_step_schema_normalizes_action_and_transform() -> None:
    step = WorkflowStepSchema(
        action=" Score ",
        payload_transform=" merge_results ",
        condition="payload['run'] == True",
    )

    assert step.action == "score"
    assert step.payload_transform == "merge_results"


def test_workflow_schema_requires_non_empty_steps() -> None:
    with pytest.raises(ValueError):
        WorkflowSchema(description="empty", steps=[])


def test_workflow_config_schema_normalizes_workflow_names() -> None:
    config = WorkflowConfigSchema(
        workflows={
            " Full_Pipeline ": WorkflowSchema(
                description="pipeline",
                steps=[WorkflowStepSchema(action="enrich")],
            )
        }
    )

    assert "full_pipeline" in config.workflows


def test_workflow_step_schema_rejects_invalid_transform() -> None:
    with pytest.raises(ValueError):
        WorkflowStepSchema(action="score", payload_transform="unknown")
