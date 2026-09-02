from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from constellation_gate.config.settings import GateSettings, _env_verifying_keys, get_settings


def test_gate_settings_normalizes_and_validates_fields() -> None:
    settings = GateSettings(
        environment="LOCAL",
        local_node="Gate",
        host="0.0.0.0",
        port=9000,
        require_signature=False,
        dev_mode=True,
        signing_key=None,
        signing_key_id=None,
        signing_algorithm=None,
        verifying_keys={},
        allowed_actions=(" Score ", "enrich"),
        allowed_packet_types=("request", "command"),
        required_idempotency_actions=(),
        allowed_clock_skew_seconds=30,
        max_packet_bytes=262_144,
        max_hop_depth=64,
        max_delegation_depth=8,
        max_attachments=32,
        max_attachment_size_bytes=10_485_760,
        attachment_allowed_schemes=(),
        allow_private_attachment_hosts=False,
        replay_enabled=True,
        verify_hop_signatures=False,
        admin_token="secret",
    )

    assert settings.environment == "local"
    assert settings.local_node == "gate"
    assert settings.allowed_actions == ("score", "enrich")
    assert settings.allowed_packet_types == ("request", "command")
    assert settings.admin_token == "secret"


# ---------------------------------------------------------------------------
# BROKEN-002: verifying_keys env loading
# ---------------------------------------------------------------------------


def test_env_verifying_keys_parses_valid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"key-1": "abc123", "key-2": "def456"}
    monkeypatch.setenv("L9_VERIFYING_KEYS_JSON", json.dumps(payload))
    result = _env_verifying_keys("L9_VERIFYING_KEYS_JSON")
    assert result == payload


def test_env_verifying_keys_empty_returns_empty_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("L9_VERIFYING_KEYS_JSON", "{}")
    result = _env_verifying_keys("L9_VERIFYING_KEYS_JSON")
    assert result == {}


def test_env_verifying_keys_missing_returns_empty_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("L9_VERIFYING_KEYS_JSON", raising=False)
    result = _env_verifying_keys("L9_VERIFYING_KEYS_JSON")
    assert result == {}


def test_env_verifying_keys_invalid_json_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("L9_VERIFYING_KEYS_JSON", "{not-json")
    with pytest.raises(ValueError, match="not valid JSON"):
        _env_verifying_keys("L9_VERIFYING_KEYS_JSON")


def test_env_verifying_keys_non_object_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("L9_VERIFYING_KEYS_JSON", '["a", "b"]')
    with pytest.raises(ValueError, match="JSON object"):
        _env_verifying_keys("L9_VERIFYING_KEYS_JSON")


def test_env_verifying_keys_blank_value_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("L9_VERIFYING_KEYS_JSON", json.dumps({"key-1": "   "}))
    with pytest.raises(ValueError, match="blank"):
        _env_verifying_keys("L9_VERIFYING_KEYS_JSON")


def test_get_settings_loads_verifying_keys_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("L9_VERIFYING_KEYS_JSON", json.dumps({"mykey": "supersecret"}))
    monkeypatch.setenv("GATE_ADMIN_TOKEN", "")
    settings = get_settings()
    assert settings.verifying_keys == {"mykey": "supersecret"}
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# BROKEN-003: admin token canonical env var
# ---------------------------------------------------------------------------


def test_get_settings_reads_gate_admin_token(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("GATE_ADMIN_TOKEN", "canonical-token")
    monkeypatch.delenv("L9_GATE_ADMIN_TOKEN", raising=False)
    monkeypatch.setenv("L9_VERIFYING_KEYS_JSON", "{}")
    settings = get_settings()
    assert settings.admin_token == "canonical-token"
    get_settings.cache_clear()


def test_get_settings_falls_back_to_l9_gate_admin_token(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    monkeypatch.delenv("GATE_ADMIN_TOKEN", raising=False)
    monkeypatch.setenv("L9_GATE_ADMIN_TOKEN", "legacy-token")
    monkeypatch.setenv("L9_VERIFYING_KEYS_JSON", "{}")
    settings = get_settings()
    assert settings.admin_token == "legacy-token"
    get_settings.cache_clear()


def test_get_settings_canonical_takes_precedence_over_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("GATE_ADMIN_TOKEN", "canonical")
    monkeypatch.setenv("L9_GATE_ADMIN_TOKEN", "legacy")
    monkeypatch.setenv("L9_VERIFYING_KEYS_JSON", "{}")
    settings = get_settings()
    assert settings.admin_token == "canonical"
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# BROKEN-001: workflow_config_path field on settings
# ---------------------------------------------------------------------------


def test_get_settings_workflow_config_path_none_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    monkeypatch.delenv("GATE_WORKFLOW_CONFIG_PATH", raising=False)
    monkeypatch.setenv("L9_VERIFYING_KEYS_JSON", "{}")
    settings = get_settings()
    assert settings.workflow_config_path is None
    get_settings.cache_clear()


def test_get_settings_workflow_config_path_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("GATE_WORKFLOW_CONFIG_PATH", "engine/workflows.yaml")
    monkeypatch.setenv("L9_VERIFYING_KEYS_JSON", "{}")
    settings = get_settings()
    assert settings.workflow_config_path == "engine/workflows.yaml"
    get_settings.cache_clear()


def test_default_port_matches_shipped_deployment_assets() -> None:
    """Every deployment asset (.env.example, compose, terraform, entrypoint) uses 9000."""
    settings = GateSettings(environment="local", local_node="gate")
    assert settings.port == 9000


def test_resilience_defaults() -> None:
    settings = GateSettings(environment="local", local_node="gate")
    assert settings.node_registry_path is None
    assert settings.health_probe_interval_seconds == 15.0
    assert settings.idempotency_ttl_seconds == 86_400.0
    assert settings.response_margin_ms == 500


def test_get_settings_reads_resilience_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("L9_ENVIRONMENT", "local")
    monkeypatch.setenv("GATE_NODE_REGISTRY_PATH", "/etc/gate/registry.yaml")
    monkeypatch.setenv("GATE_HEALTH_PROBE_INTERVAL_SECONDS", "2.5")
    monkeypatch.setenv("GATE_IDEMPOTENCY_TTL_SECONDS", "600")
    monkeypatch.setenv("GATE_RESPONSE_MARGIN_MS", "250")
    get_settings.cache_clear()
    try:
        settings = get_settings()
    finally:
        get_settings.cache_clear()
    assert settings.node_registry_path == "/etc/gate/registry.yaml"
    assert settings.health_probe_interval_seconds == 2.5
    assert settings.idempotency_ttl_seconds == 600.0
    assert settings.response_margin_ms == 250


def test_negative_probe_interval_and_zero_ttl_are_rejected() -> None:
    with pytest.raises(ValidationError):
        GateSettings(environment="local", local_node="gate", health_probe_interval_seconds=-1)
    with pytest.raises(ValidationError):
        GateSettings(environment="local", local_node="gate", idempotency_ttl_seconds=0)
    with pytest.raises(ValidationError):
        GateSettings(environment="local", local_node="gate", response_margin_ms=-1)
