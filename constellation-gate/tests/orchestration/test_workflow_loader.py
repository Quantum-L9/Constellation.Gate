"""Tests for BROKEN-001: _load_workflow_definitions."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from constellation_gate.api.dependencies import _load_workflow_definitions


def test_load_workflow_definitions_valid(tmp_path: Path) -> None:
    config_file = tmp_path / "workflows.yaml"
    config_file.write_text(
        textwrap.dedent("""\
            workflows:
              full_pipeline:
                description: "Enrich then score"
                steps:
                  - name: enrich-step
                    action: enrich
                    merge_strategy: merge_payload
                  - name: score-step
                    action: score
                    merge_strategy: merge_results
        """)
    )
    defs = _load_workflow_definitions(str(config_file))
    assert "full_pipeline" in defs
    assert len(defs["full_pipeline"].steps) == 2
    assert defs["full_pipeline"].steps[0].action == "enrich"


def test_load_workflow_definitions_empty_workflows(tmp_path: Path) -> None:
    config_file = tmp_path / "workflows.yaml"
    config_file.write_text("workflows: {}\n")
    defs = _load_workflow_definitions(str(config_file))
    assert defs == {}


def test_load_workflow_definitions_null_file(tmp_path: Path) -> None:
    config_file = tmp_path / "workflows.yaml"
    config_file.write_text("")
    defs = _load_workflow_definitions(str(config_file))
    assert defs == {}


def test_load_workflow_definitions_missing_file_raises() -> None:
    with pytest.raises(ValueError, match="does not exist"):
        _load_workflow_definitions("/nonexistent/path/workflows.yaml")


def test_load_workflow_definitions_invalid_yaml_raises(tmp_path: Path) -> None:
    config_file = tmp_path / "workflows.yaml"
    config_file.write_text(": bad: yaml: [unclosed")
    with pytest.raises(ValueError, match="not valid YAML"):
        _load_workflow_definitions(str(config_file))


def test_load_workflow_definitions_invalid_step_raises(tmp_path: Path) -> None:
    config_file = tmp_path / "workflows.yaml"
    config_file.write_text(
        textwrap.dedent("""\
            workflows:
              bad_flow:
                steps:
                  - name: step-1
                    action: ""
        """)
    )
    with pytest.raises(ValueError, match="failed validation"):
        _load_workflow_definitions(str(config_file))


def test_load_workflow_definitions_legacy_step_syntax(tmp_path: Path) -> None:
    """Legacy steps using payload_transform and no name must normalize and load."""
    config_file = tmp_path / "workflows.yaml"
    config_file.write_text(
        textwrap.dedent("""\
            workflows:
              full_pipeline:
                description: legacy syntax
                steps:
                  - action: enrich
                    payload_transform: merge_payload
                  - action: score
                    payload_transform: merge_results
        """)
    )
    defs = _load_workflow_definitions(str(config_file))
    steps = defs["full_pipeline"].steps
    assert [s.name for s in steps] == ["enrich-1", "score-2"]
    assert [s.merge_strategy for s in steps] == ["merge_payload", "merge_results"]


def test_load_workflow_definitions_shipped_config_loads() -> None:
    """The repository's bundled workflows.yaml must load without error."""
    shipped = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "constellation_gate"
        / "config"
        / "workflows.yaml"
    )
    defs = _load_workflow_definitions(str(shipped))
    assert "full_pipeline" in defs
    assert all(step.name for wf in defs.values() for step in wf.steps)
