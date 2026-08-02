"""Sanitized capability descriptors — no topology or credentials."""

from __future__ import annotations

from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, model_validator

FORBIDDEN_CAPABILITY_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "internal_url",
        "url",
        "host",
        "port",
        "credential",
        "credentials",
        "token",
        "secret",
        "password",
        "healthy",
        "health",
        "health_endpoint",
        "active_requests",
        "max_concurrent",
        "timeout_ms",
        "node_name",
        "nodes",
        "registry",
        "registry_key",
        "topology",
        "load",
        "live_load",
    }
)

CAPABILITY_CONTRACT_VERSION: Final[str] = "1.0.0"


class CapabilityDescriptor(BaseModel):
    """Public capability projection for one action.

    Intentionally excludes topology, credentials, and live load.
    """

    model_config = ConfigDict(extra="forbid")

    action: str
    owner: str | None = None
    contract_version: str = CAPABILITY_CONTRACT_VERSION
    advertised: bool = True

    @model_validator(mode="before")
    @classmethod
    def reject_forbidden_fields(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        for key in value:
            normalized = str(key).strip().lower()
            if normalized in FORBIDDEN_CAPABILITY_FIELDS:
                raise ValueError(
                    f"capability descriptor must not include topology/sensitive field: {key}"
                )
            # Nested payloads are not allowed to smuggle topology either.
            nested = value[key]
            if isinstance(nested, dict):
                for nested_key in nested:
                    if str(nested_key).strip().lower() in FORBIDDEN_CAPABILITY_FIELDS:
                        raise ValueError(
                            f"capability descriptor must not include nested "
                            f"topology/sensitive field: {nested_key}"
                        )
        return value


class CapabilityListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: str = CAPABILITY_CONTRACT_VERSION
    etag: str
    capabilities: list[CapabilityDescriptor] = Field(default_factory=list)
