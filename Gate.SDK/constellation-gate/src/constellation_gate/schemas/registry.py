from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator


class NodeRegistrationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    internal_url: str
    supported_actions: list[str]
    priority_class: str = "P2"
    max_concurrent: int = Field(default=50, ge=1)
    health_endpoint: str = "/v1/health"
    timeout_ms: int = Field(default=30_000, ge=1)
    metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("internal_url")
    @classmethod
    def validate_internal_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if not normalized:
            raise ValueError("internal_url must not be empty")
        if not (normalized.startswith("http://") or normalized.startswith("https://")):
            raise ValueError("internal_url must start with http:// or https://")
        return normalized

    @field_validator("supported_actions")
    @classmethod
    def validate_supported_actions(cls, value: list[str]) -> list[str]:
        normalized = [item.strip().lower() for item in value if item.strip()]
        if not normalized:
            raise ValueError("supported_actions must not be empty")
        if len(set(normalized)) != len(normalized):
            raise ValueError("supported_actions must not contain duplicates")
        return normalized

    @field_validator("priority_class")
    @classmethod
    def validate_priority_class(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in {"P0", "P1", "P2", "P3"}:
            raise ValueError("priority_class must be one of P0, P1, P2, P3")
        return normalized

    @field_validator("health_endpoint")
    @classmethod
    def validate_health_endpoint(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.startswith("/"):
            raise ValueError("health_endpoint must start with /")
        return normalized


class RegisterNodesRequest(RootModel[dict[str, NodeRegistrationInput]]):
    pass


class NodeRegistrationStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_name: str
    healthy: bool
    registered: bool = True


class RegisterNodesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registered: list[NodeRegistrationStatus]
    total_nodes: int = Field(ge=0)
