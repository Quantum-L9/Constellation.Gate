from __future__ import annotations

from constellation_gate.config.settings import GateSettings


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
