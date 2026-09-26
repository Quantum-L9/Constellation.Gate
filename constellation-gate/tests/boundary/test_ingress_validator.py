from __future__ import annotations

import pytest
from constellation_node_sdk.transport.packet import create_transport_packet
from constellation_node_sdk.transport.provenance import RoutingProvenance

from constellation_gate.boundary.ingress_validator import IngressValidationError, IngressValidator


def test_ingress_validator_accepts_canonical_client_request_to_gate() -> None:
    validator = IngressValidator(local_node="gate")

    packet = create_transport_packet(
        action="enrich",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )

    validated = validator.validate(packet.model_dump_json_dict())

    assert validated.header.action == "enrich"
    assert validated.address.destination_node == "gate"


def test_ingress_validator_rejects_non_canonical_request_body() -> None:
    validator = IngressValidator(local_node="gate")

    with pytest.raises(IngressValidationError):
        validator.validate({"action": "enrich", "payload": {"entity_id": "42"}})


def test_ingress_validator_rejects_node_to_peer_routing() -> None:
    validator = IngressValidator(
        local_node="gate",
        known_nodes_provider=lambda: {"orchestrator", "enrich"},
    )

    packet = create_transport_packet(
        action="enrich",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="enrich",
        source_node="orchestrator",
        reply_to="orchestrator",
        provenance=RoutingProvenance(
            origin_kind="node",
            requested_action="enrich",
            resolved_by_gate=False,
            original_source_node="orchestrator",
        ),
    )

    with pytest.raises(IngressValidationError):
        validator.validate(packet.model_dump_json_dict())


# ── Per-key action scope (L9_KEY_ALLOWED_ACTIONS_JSON) ───────────────────────

_KEYS = {"odoo-k1": "odoo-secret-0123456789", "eie-k1": "eie-secret-0123456789"}


def _signed(action: str, key_id: str) -> dict:
    from constellation_node_sdk.security.signing import sign_transport_packet

    packet = create_transport_packet(
        action=action,
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="odoo",
        reply_to="odoo",
    )
    signed = sign_transport_packet(
        packet, key=_KEYS[key_id], key_id=key_id, algorithm="hmac-sha256"
    )
    return signed.model_dump_json_dict()


def _scoped_validator() -> IngressValidator:
    return IngressValidator(
        local_node="gate",
        require_signature=True,
        key_resolver=_KEYS.get,
        key_allowed_actions={"odoo-k1": ("converge", "match")},
    )


@pytest.mark.parametrize("action", ["converge", "match"])
def test_scoped_key_may_invoke_its_listed_actions(action: str) -> None:
    validated = _scoped_validator().validate(_signed(action, "odoo-k1"))

    assert validated.header.action == action


def test_scoped_key_is_refused_an_action_outside_its_scope() -> None:
    from constellation_gate.boundary.ingress_validator import IngressAuthorizationError

    with pytest.raises(IngressAuthorizationError, match="'odoo-k1'.*'sync'"):
        _scoped_validator().validate(_signed("sync", "odoo-k1"))


def test_unscoped_key_keeps_unrestricted_access() -> None:
    validated = _scoped_validator().validate(_signed("sync", "eie-k1"))

    assert validated.header.action == "sync"


def test_scope_is_not_consulted_before_the_signature_is_verified() -> None:
    from constellation_node_sdk.security.signing import sign_transport_packet

    packet = create_transport_packet(
        action="sync",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="odoo",
        reply_to="odoo",
    )
    forged = sign_transport_packet(
        packet, key="not-the-real-secret", key_id="odoo-k1", algorithm="hmac-sha256"
    )

    # A forged signature is an invalid packet (400), not an authorization verdict.
    with pytest.raises(IngressValidationError):
        _scoped_validator().validate(forged.model_dump_json_dict())
