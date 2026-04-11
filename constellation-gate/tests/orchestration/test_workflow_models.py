from __future__ import annotations

import pytest

from constellation_gate.orchestration.workflow_models import WorkflowDefinition, WorkflowStep


def test_workflow_definition_requires_unique_step_names() -> None:
    with pytest.raises(ValueError):
        WorkflowDefinition(
            name="full_pipeline",
            steps=(
                WorkflowStep(name="enrich", action="enrich"),
                WorkflowStep(name="enrich", action="score"),
            ),
        )


def test_workflow_step_validates_merge_strategy() -> None:
    with pytest.raises(ValueError):
        WorkflowStep(
            name="score",
            action="score",
            merge_strategy="unknown",
        )


def test_workflow_definition_accepts_valid_steps() -> None:
    definition = WorkflowDefinition(
        name="full_pipeline",
        description="Composite enrichment + scoring",
        steps=(
            WorkflowStep(name="enrich", action="enrich"),
            WorkflowStep(name="score", action="score", merge_strategy="merge_results"),
        ),
    )

    assert definition.name == "full_pipeline"
    assert len(definition.steps) == 2
    assert definition.steps[1].merge_strategy == "merge_results"
