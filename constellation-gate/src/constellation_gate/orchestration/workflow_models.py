from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


_ALLOWED_MERGE_STRATEGIES = {"identity", "merge_payload", "merge_results"}


class WorkflowStep(BaseModel):
    """
    Canonical Gate workflow step definition.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    action: str
    timeout_ms: int | None = Field(default=None, ge=1)
    merge_strategy: str = "merge_payload"
    condition: str | None = None

    @field_validator("name", "action", "condition")
    @classmethod
    def validate_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("string fields must not be blank")
        return normalized

    @field_validator("merge_strategy")
    @classmethod
    def validate_merge_strategy(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_MERGE_STRATEGIES:
            raise ValueError(f"merge_strategy must be one of {sorted(_ALLOWED_MERGE_STRATEGIES)}")
        return normalized


class WorkflowDefinition(BaseModel):
    """
    Sequential workflow definition resolved by Gate for composite actions.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    steps: tuple[WorkflowStep, ...]

    @field_validator("name", "description")
    @classmethod
    def validate_strings(cls, value: str) -> str:
        normalized = value.strip()
        if value == "":
            return value
        if not normalized and value != "":
            raise ValueError("string fields must not be blank")
        return normalized

    @field_validator("steps", mode="before")
    @classmethod
    def coerce_steps(cls, value: tuple[WorkflowStep, ...] | list[WorkflowStep]) -> tuple[WorkflowStep, ...]:
        if isinstance(value, list):
            return tuple(value)
        return value

    @field_validator("steps")
    @classmethod
    def validate_steps(cls, value: tuple[WorkflowStep, ...]) -> tuple[WorkflowStep, ...]:
        if not value:
            raise ValueError("workflow must contain at least one step")
        names = [step.name.strip().lower() for step in value]
        if len(set(names)) != len(names):
            raise ValueError("workflow step names must be unique")
        return value
