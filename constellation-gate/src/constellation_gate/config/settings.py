from __future__ import annotations

import os
from functools import lru_cache

from pydantic import BaseModel, ConfigDict, Field, field_validator

_ALLOWED_ENVIRONMENTS = {"local", "dev", "test", "staging", "prod"}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_tuple(name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None:
        return default
    return tuple(item.strip().lower() for item in raw.split(",") if item.strip())


class GateSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    environment: str = "local"
    local_node: str = "gate"

    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)

    require_signature: bool = False
    dev_mode: bool = False
    signing_key: str | None = None
    signing_key_id: str | None = None
    signing_algorithm: str | None = None
    verifying_keys: dict[str, str] = Field(default_factory=dict)

    allowed_actions: tuple[str, ...] = ()
    allowed_packet_types: tuple[str, ...] = ("request", "command", "delegation", "replay_request")
    required_idempotency_actions: tuple[str, ...] = ()

    allowed_clock_skew_seconds: int = Field(default=30, ge=0)
    max_packet_bytes: int = Field(default=262_144, ge=1024)
    max_hop_depth: int = Field(default=64, ge=1)
    max_delegation_depth: int = Field(default=8, ge=1)
    max_attachments: int = Field(default=32, ge=0)
    max_attachment_size_bytes: int = Field(default=10_485_760, ge=0)
    attachment_allowed_schemes: tuple[str, ...] = ()
    allow_private_attachment_hosts: bool = False

    replay_enabled: bool = True
    verify_hop_signatures: bool = False
    admin_token: str | None = None

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_ENVIRONMENTS:
            raise ValueError(f"environment must be one of {sorted(_ALLOWED_ENVIRONMENTS)}")
        return normalized

    @field_validator("local_node", "host")
    @classmethod
    def validate_required_strings(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized

    @field_validator("signing_key_id", "signing_algorithm", "admin_token")
    @classmethod
    def validate_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("optional string fields must not be blank")
        return normalized

    @field_validator("allowed_actions", "allowed_packet_types", "required_idempotency_actions", "attachment_allowed_schemes")
    @classmethod
    def validate_tuples(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip().lower() for item in value if item.strip())
        if len(set(normalized)) != len(normalized):
            raise ValueError("tuple entries must not contain duplicates")
        return normalized

    @field_validator("verifying_keys")
    @classmethod
    def validate_verifying_keys(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for key_id, key_value in value.items():
            rendered_key = key_id.strip()
            rendered_value = key_value.strip()
            if not rendered_key or not rendered_value:
                raise ValueError("verifying_keys must not contain blank keys or values")
            normalized[rendered_key] = rendered_value
        return normalized

    def resolve_verifying_key(self, key_id: str | None) -> str | bytes | None:
        if key_id is None:
            return None
        if key_id in self.verifying_keys:
            return self.verifying_keys[key_id]
        if self.signing_key_id is not None and key_id == self.signing_key_id and self.signing_key is not None:
            return self.signing_key
        return None


@lru_cache
def get_settings() -> GateSettings:
    return GateSettings(
        environment=os.getenv("L9_ENVIRONMENT", "local"),
        local_node=os.getenv("GATE_LOCAL_NODE", "gate"),
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        require_signature=_env_bool("L9_REQUIRE_SIGNATURE", False),
        dev_mode=_env_bool("L9_DEV_MODE", False),
        signing_key=os.getenv("L9_SIGNING_KEY") or os.getenv("L9_SIGNING_SECRET"),
        signing_key_id=os.getenv("L9_SIGNING_KEY_ID"),
        signing_algorithm=os.getenv("L9_SIGNING_ALGORITHM"),
        verifying_keys={},
        allowed_actions=_env_tuple("L9_ALLOWED_ACTIONS"),
        allowed_packet_types=_env_tuple("L9_ALLOWED_PACKET_TYPES", ("request", "command", "delegation", "replay_request")),
        required_idempotency_actions=_env_tuple("L9_REQUIRE_IDEMPOTENCY_FOR_ACTIONS"),
        allowed_clock_skew_seconds=int(os.getenv("L9_ALLOWED_CLOCK_SKEW_SECONDS", "30")),
        max_packet_bytes=int(os.getenv("L9_MAX_PACKET_BYTES", "262144")),
        max_hop_depth=int(os.getenv("L9_MAX_HOP_DEPTH", "64")),
        max_delegation_depth=int(os.getenv("L9_MAX_DELEGATION_DEPTH", "8")),
        max_attachments=int(os.getenv("L9_MAX_ATTACHMENTS", "32")),
        max_attachment_size_bytes=int(os.getenv("L9_MAX_ATTACHMENT_SIZE_BYTES", "10485760")),
        attachment_allowed_schemes=_env_tuple("L9_ATTACHMENT_ALLOWED_SCHEMES"),
        allow_private_attachment_hosts=_env_bool("L9_ALLOW_PRIVATE_ATTACHMENT_HOSTS", False),
        replay_enabled=_env_bool("L9_REPLAY_ENABLED", True),
        verify_hop_signatures=_env_bool("L9_VERIFY_HOP_SIGNATURES", False),
        admin_token=os.getenv("L9_GATE_ADMIN_TOKEN"),
    )
