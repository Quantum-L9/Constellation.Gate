from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WorkflowStepSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str
    timeout_ms: int | None = Field(default=None, ge=1)
    payload_transform: str = "merge_payload"
    condition: str | None = None
    target_node: str | None = None

    @field_validator("action")
    @classmethod
    def validate_action(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("action must not be blank")
        return normalized

    @field_validator("payload_transform")
    @classmethod
    def validate_payload_transform(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"identity", "merge_payload", "merge_results"}:
            raise ValueError(
                "payload_transform must be one of identity, merge_payload, merge_results"
            )
        return normalized

    @field_validator("condition", "target_node")
    @classmethod
    def validate_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("optional string fields must not be blank")
        return normalized


class WorkflowSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = ""
    steps: list[WorkflowStepSchema]

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        return value.strip()

    @field_validator("steps")
    @classmethod
    def validate_steps(cls, value: list[WorkflowStepSchema]) -> list[WorkflowStepSchema]:
        if not value:
            raise ValueError("workflow must contain at least one step")
        return value


class WorkflowConfigSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflows: dict[str, WorkflowSchema]

    @field_validator("workflows")
    @classmethod
    def validate_workflows(cls, value: dict[str, WorkflowSchema]) -> dict[str, WorkflowSchema]:
        if not value:
            raise ValueError("workflows must not be empty")
        normalized: dict[str, WorkflowSchema] = {}
        for name, workflow in value.items():
            normalized_name = name.strip().lower()
            if not normalized_name:
                raise ValueError("workflow names must not be blank")
            normalized[normalized_name] = workflow
        return normalized
