from __future__ import annotations

import json
import os
from functools import lru_cache

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_ALLOWED_ENVIRONMENTS = {"local", "dev", "test", "staging", "prod"}

# Environments where Gate is reachable by something other than a developer's
# laptop. In these, an unauthenticated ingress is a NO_GO, not a default.
_TRUSTED_INGRESS_REQUIRED_ENVIRONMENTS = frozenset({"staging", "prod"})


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


def _env_verifying_keys(name: str) -> dict[str, str]:
    """Parse JSON object from env var into verifying_keys dict.

    Returns empty dict on missing or blank value.
    Raises ValueError on malformed JSON or non-string values so that startup
    fails fast rather than silently disabling signature verification.
    """
    raw = os.getenv(name, "").strip()
    if not raw or raw == "{}":
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{name} must be a JSON object")
    result: dict[str, str] = {}
    for key_id, key_value in parsed.items():
        if not isinstance(key_id, str) or not isinstance(key_value, str):
            raise ValueError(f"{name} keys and values must all be strings")
        k = key_id.strip()
        v = key_value.strip()
        if not k or not v:
            raise ValueError(f"{name} must not contain blank key_id or key_value")
        result[k] = v
    return result


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

    # Actions this deployment must be able to route before it is considered
    # ready. Empty = no declared routing requirement.
    required_ready_actions: tuple[str, ...] = ()

    # Explicit operator assertion that ingress is fronted by an authenticated
    # network boundary (service mesh mTLS / private ingress). This does not relax
    # packet validation; it only records which trust mechanism is authoritative
    # so a deployed environment cannot end up with neither.
    trusted_network_ingress: bool = False

    # BROKEN-001: path to workflow definitions YAML file; empty/unset = workflows disabled
    workflow_config_path: str | None = None

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

    @field_validator("workflow_config_path")
    @classmethod
    def validate_workflow_config_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("workflow_config_path must not be blank")
        return normalized

    @field_validator(
        "allowed_actions",
        "allowed_packet_types",
        "required_idempotency_actions",
        "required_ready_actions",
        "attachment_allowed_schemes",
    )
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

    @model_validator(mode="after")
    def enforce_production_ingress_trust(self) -> GateSettings:
        """Fail closed when a deployed environment has no ingress trust boundary.

        Gate's ingress accepts a canonical TransportPacket over HTTP. The packet
        model proves internal integrity (payload_hash / transport_hash) but a
        hash any caller can recompute is not authentication -- it says the packet
        is well-formed, not that it came from someone entitled to route work.

        Signature verification is the only trust boundary this repository can
        actually enforce. If an operator asserts that an authenticated network
        boundary (mesh mTLS, private ingress) is the real control, that is a
        deliberate, named decision -- so it must be stated explicitly via
        L9_TRUSTED_NETWORK_INGRESS rather than obtained by leaving a default at
        false. Silent unauthenticated production ingress is what this rejects.
        """
        if self.environment not in _TRUSTED_INGRESS_REQUIRED_ENVIRONMENTS:
            return self

        if self.dev_mode:
            raise ValueError(
                f"dev_mode must be disabled in environment {self.environment!r} "
                "(set L9_DEV_MODE=false)"
            )

        if self.trusted_network_ingress:
            # Operator has asserted an external authenticated boundary. Packet
            # validation stays on as defense in depth; nothing is relaxed here.
            return self

        if not self.require_signature:
            raise ValueError(
                f"environment {self.environment!r} requires an ingress trust boundary: "
                "set L9_REQUIRE_SIGNATURE=true (with L9_VERIFYING_KEYS_JSON), or assert "
                "an authenticated network boundary with L9_TRUSTED_NETWORK_INGRESS=true"
            )

        if not self.verifying_keys and self.signing_key is None:
            raise ValueError(
                f"environment {self.environment!r} sets require_signature=true but no "
                "verifying key material is configured; signature verification would "
                "reject every packet. Set L9_VERIFYING_KEYS_JSON."
            )

        return self

    def resolve_verifying_key(self, key_id: str | None) -> str | bytes | None:
        if key_id is None:
            return None
        if key_id in self.verifying_keys:
            return self.verifying_keys[key_id]
        if (
            self.signing_key_id is not None
            and key_id == self.signing_key_id
            and self.signing_key is not None
        ):
            return self.signing_key
        return None


@lru_cache
def get_settings() -> GateSettings:
    # BROKEN-003: GATE_ADMIN_TOKEN is the canonical name (matches SDK).
    # L9_GATE_ADMIN_TOKEN is accepted as a backward-compatible fallback.
    admin_token = os.getenv("GATE_ADMIN_TOKEN") or os.getenv("L9_GATE_ADMIN_TOKEN") or None

    # BROKEN-002: parse verifying keys from env; fails fast on malformed JSON
    verifying_keys = _env_verifying_keys("L9_VERIFYING_KEYS_JSON")

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
        verifying_keys=verifying_keys,
        allowed_actions=_env_tuple("L9_ALLOWED_ACTIONS"),
        allowed_packet_types=_env_tuple(
            "L9_ALLOWED_PACKET_TYPES",
            ("request", "command", "delegation", "replay_request"),
        ),
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
        admin_token=admin_token,
        required_ready_actions=_env_tuple("L9_REQUIRED_READY_ACTIONS"),
        trusted_network_ingress=_env_bool("L9_TRUSTED_NETWORK_INGRESS", False),
        # BROKEN-001: optional workflow YAML path; None = workflows disabled
        workflow_config_path=os.getenv("GATE_WORKFLOW_CONFIG_PATH") or None,
    )
