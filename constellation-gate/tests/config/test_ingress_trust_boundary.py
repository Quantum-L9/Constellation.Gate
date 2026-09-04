"""ADR-GATE-012: production ingress requires an authoritative trust boundary.

Structural packet validity is not authentication. The shipped Terraform defaults
`allowed_cidrs` to 0.0.0.0/0, so a staging/prod Gate with `require_signature`
off would accept any well-formed packet from anywhere on the internet.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from constellation_gate.config.settings import GateSettings


def _settings(**overrides) -> GateSettings:
    base = {"environment": "prod", "local_node": "gate", "admin_token": "admin-secret"}
    return GateSettings(**{**base, **overrides})


@pytest.mark.parametrize("environment", ["staging", "prod"])
def test_trust_requiring_environment_rejects_unauthenticated_ingress(environment: str) -> None:
    with pytest.raises(ValidationError, match="no proven ingress trust boundary"):
        _settings(environment=environment, require_signature=False)


@pytest.mark.parametrize("environment", ["local", "dev", "test"])
def test_non_production_environments_are_unaffected(environment: str) -> None:
    settings = _settings(environment=environment, require_signature=False)
    assert settings.environment == environment


def test_signature_boundary_satisfies_production() -> None:
    settings = _settings(
        require_signature=True,
        verifying_keys={"key-1": "secret-material"},
    )
    assert settings.require_signature is True


def test_require_signature_without_keys_is_rejected() -> None:
    """Signature enforcement with no key verifies nothing."""
    with pytest.raises(ValidationError, match="no key is available to verify against"):
        _settings(require_signature=True, verifying_keys={})


def test_declared_network_boundary_requires_evidence() -> None:
    with pytest.raises(ValidationError, match="requires"):
        _settings(trusted_ingress_boundary="network")


def test_declared_network_boundary_with_evidence_is_accepted() -> None:
    settings = _settings(
        trusted_ingress_boundary="network",
        trusted_ingress_boundary_evidence="istio mTLS mesh; gate port private-only",
    )
    assert settings.trusted_ingress_boundary == "network"


def test_dev_mode_is_refused_in_production() -> None:
    with pytest.raises(ValidationError, match="dev mode relaxes canonical packet validation"):
        _settings(
            dev_mode=True,
            require_signature=True,
            verifying_keys={"key-1": "secret-material"},
        )


def test_unknown_boundary_mode_is_rejected() -> None:
    with pytest.raises(ValidationError, match="trusted_ingress_boundary must be one of"):
        _settings(trusted_ingress_boundary="vibes")


def test_network_boundary_declaration_does_not_leak_into_signature_config() -> None:
    """Declaring a network boundary must not silently imply signature verification."""
    settings = _settings(
        trusted_ingress_boundary="network",
        trusted_ingress_boundary_evidence="private ingress only",
    )
    assert settings.require_signature is False


@pytest.mark.parametrize("environment", ["staging", "prod"])
def test_trust_requiring_environment_requires_admin_token(environment: str) -> None:
    """A satisfied ingress boundary is not enough: registration is routing authority."""
    with pytest.raises(ValidationError, match="requires GATE_ADMIN_TOKEN"):
        _settings(
            environment=environment,
            admin_token=None,
            require_signature=True,
            verifying_keys={"key-1": "secret-material"},
        )


@pytest.mark.parametrize("environment", ["local", "dev", "test"])
def test_admin_token_is_optional_outside_trust_requiring_environments(environment: str) -> None:
    settings = _settings(environment=environment, admin_token=None)
    assert settings.admin_token is None


def test_missing_boundary_is_reported_before_missing_admin_token() -> None:
    """When both are absent the broader finding (no ingress boundary) is the one raised."""
    with pytest.raises(ValidationError, match="no proven ingress trust boundary"):
        _settings(admin_token=None, require_signature=False)
