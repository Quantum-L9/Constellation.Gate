"""A deployed environment must have a named ingress trust boundary.

Gate accepts a canonical TransportPacket over HTTP. The packet model proves
internal integrity (payload_hash / transport_hash), but a hash any caller can
recompute is not authentication -- it says the packet is well-formed, not that
whoever sent it is entitled to route work through Gate.

So staging and prod must either verify signatures, or have an operator
explicitly assert an authenticated network boundary. What they may not do is
end up with neither by leaving a default at false.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from constellation_gate.config.settings import GateSettings


@pytest.mark.parametrize("environment", ["local", "dev", "test"])
def test_developer_environments_stay_permissive(environment: str) -> None:
    settings = GateSettings(environment=environment, dev_mode=True)
    assert settings.environment == environment
    assert settings.require_signature is False


@pytest.mark.parametrize("environment", ["staging", "prod"])
def test_deployed_environment_rejects_unauthenticated_ingress(environment: str) -> None:
    with pytest.raises(ValidationError, match="requires an ingress trust boundary"):
        GateSettings(environment=environment)


@pytest.mark.parametrize("environment", ["staging", "prod"])
def test_deployed_environment_rejects_dev_mode(environment: str) -> None:
    with pytest.raises(ValidationError, match="dev_mode must be disabled"):
        GateSettings(environment=environment, dev_mode=True, trusted_network_ingress=True)


@pytest.mark.parametrize("environment", ["staging", "prod"])
def test_require_signature_without_key_material_is_rejected(environment: str) -> None:
    """Signature verification with no keys would reject every packet."""
    with pytest.raises(ValidationError, match="no verifying key material"):
        GateSettings(environment=environment, require_signature=True)


@pytest.mark.parametrize("environment", ["staging", "prod"])
def test_signature_boundary_with_keys_is_accepted(environment: str) -> None:
    settings = GateSettings(
        environment=environment,
        require_signature=True,
        verifying_keys={"key-1": "secret"},
    )
    assert settings.require_signature is True


@pytest.mark.parametrize("environment", ["staging", "prod"])
def test_signing_key_alone_satisfies_key_material(environment: str) -> None:
    settings = GateSettings(
        environment=environment,
        require_signature=True,
        signing_key="secret",
        signing_key_id="key-1",
        signing_algorithm="hmac-sha256",
    )
    assert settings.resolve_verifying_key("key-1") == "secret"


@pytest.mark.parametrize("environment", ["staging", "prod"])
def test_asserted_network_boundary_is_accepted_and_relaxes_nothing(environment: str) -> None:
    """The assertion records which mechanism is authoritative; it disables nothing.

    Packet validation stays on as defense in depth.
    """
    settings = GateSettings(environment=environment, trusted_network_ingress=True)
    assert settings.trusted_network_ingress is True
    assert settings.replay_enabled is True


def test_env_var_drives_the_network_boundary_assertion(monkeypatch: pytest.MonkeyPatch) -> None:
    from constellation_gate.config.settings import get_settings

    monkeypatch.setenv("L9_ENVIRONMENT", "prod")
    monkeypatch.setenv("L9_TRUSTED_NETWORK_INGRESS", "true")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.environment == "prod"
        assert settings.trusted_network_ingress is True
    finally:
        get_settings.cache_clear()


def test_prod_without_any_boundary_fails_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    from constellation_gate.config.settings import get_settings

    monkeypatch.setenv("L9_ENVIRONMENT", "prod")
    monkeypatch.delenv("L9_TRUSTED_NETWORK_INGRESS", raising=False)
    monkeypatch.delenv("L9_REQUIRE_SIGNATURE", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(ValidationError):
            get_settings()
    finally:
        get_settings.cache_clear()
