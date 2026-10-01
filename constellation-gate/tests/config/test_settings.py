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


def test_signing_key_defaults_the_algorithm() -> None:
    """The dispatch transport needs key + id + algorithm; the algorithm has one sane default."""
    settings = GateSettings(
        environment="local", local_node="gate", signing_key="material", signing_key_id="gate-k1"
    )
    assert settings.signing_algorithm == "hmac-sha256"


def test_signing_key_without_id_fails_at_startup() -> None:
    with pytest.raises(ValidationError, match="L9_SIGNING_KEY_ID is empty"):
        GateSettings(environment="local", local_node="gate", signing_key="material")


def test_signing_key_id_without_key_fails_at_startup() -> None:
    with pytest.raises(ValidationError, match="L9_SIGNING_KEY is empty"):
        GateSettings(environment="local", local_node="gate", signing_key_id="gate-k1")


def _odoo_record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "node": " Odoo ",
        "kind": "Consumer",
        "tenants": [" Tenant-A "],
        "actions": ["Converge", " match "],
    }
    record.update(overrides)
    return record


def test_env_caller_policies_parse_and_normalize(monkeypatch: pytest.MonkeyPatch) -> None:
    from constellation_gate.config.settings import CallerPolicy, _env_caller_policies

    monkeypatch.setenv(
        "L9_KEY_ALLOWED_ACTIONS_JSON",
        json.dumps({" odoo-k1 ": _odoo_record()}),
    )

    parsed = _env_caller_policies("L9_KEY_ALLOWED_ACTIONS_JSON")

    assert parsed == {
        "odoo-k1": CallerPolicy(
            node="odoo",
            kind="consumer",
            tenants=("tenant-a",),
            actions=("converge", "match"),
        )
    }


def test_env_caller_policies_missing_returns_empty_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    from constellation_gate.config.settings import _env_caller_policies

    monkeypatch.delenv("L9_KEY_ALLOWED_ACTIONS_JSON", raising=False)

    assert _env_caller_policies("L9_KEY_ALLOWED_ACTIONS_JSON") == {}


@pytest.mark.parametrize(
    "raw",
    [
        "{not-json",
        '["converge"]',
        '{"odoo-k1": ["converge", "match"]}',
        '{"odoo-k1": "converge"}',
        json.dumps({"odoo-k1": _odoo_record(actions=[])}),
        json.dumps({"odoo-k1": _odoo_record(kind="admin")}),
        json.dumps({"odoo-k1": _odoo_record(tenants=[""])}),
    ],
)
def test_env_caller_policies_reject_malformed_records(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    from constellation_gate.config.settings import _env_caller_policies

    monkeypatch.setenv("L9_KEY_ALLOWED_ACTIONS_JSON", raw)

    with pytest.raises(ValueError):
        _env_caller_policies("L9_KEY_ALLOWED_ACTIONS_JSON")


def test_settings_refuse_policies_without_mandatory_signatures() -> None:
    from constellation_gate.config.settings import CallerPolicy

    with pytest.raises(ValueError, match="L9_REQUIRE_SIGNATURE"):
        GateSettings(
            require_signature=False,
            verifying_keys={"odoo-k1": "secret"},
            caller_policies={
                "odoo-k1": CallerPolicy(
                    node="odoo", kind="consumer", tenants=("tenant-a",), actions=("converge",)
                )
            },
        )


def test_settings_refuse_a_policy_for_an_unknown_key_id() -> None:
    from constellation_gate.config.settings import CallerPolicy

    with pytest.raises(ValueError, match="odoo-typo"):
        GateSettings(
            require_signature=True,
            verifying_keys={"odoo-k1": "secret"},
            caller_policies={
                "odoo-typo": CallerPolicy(
                    node="odoo", kind="consumer", tenants=("tenant-a",), actions=("converge",)
                )
            },
        )


def test_local_settings_load_with_an_empty_caller_policy() -> None:
    settings = GateSettings(environment="local", verifying_keys={"odoo-k1": "secret"})

    assert settings.caller_policies == {}
    assert settings.caller_policy_required is False


@pytest.mark.parametrize("environment", ["staging", "prod"])
def test_trust_environments_refuse_a_verifying_key_with_no_caller_policy(environment: str) -> None:
    with pytest.raises(ValidationError, match="missing"):
        GateSettings(
            environment=environment,
            require_signature=True,
            verifying_keys={"odoo-k1": "secret"},
            admin_token="admin-secret",
        )


def test_get_settings_loads_caller_policies_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from constellation_gate.config.settings import CallerPolicy

    get_settings.cache_clear()
    monkeypatch.setenv("L9_VERIFYING_KEYS_JSON", json.dumps({"odoo-k1": "secret"}))
    monkeypatch.setenv(
        "L9_KEY_ALLOWED_ACTIONS_JSON",
        json.dumps({"odoo-k1": _odoo_record()}),
    )
    monkeypatch.setenv("L9_REQUIRE_SIGNATURE", "true")
    try:
        assert get_settings().caller_policies == {
            "odoo-k1": CallerPolicy(
                node="odoo",
                kind="consumer",
                tenants=("tenant-a",),
                actions=("converge", "match"),
            )
        }
    finally:
        get_settings.cache_clear()
