from __future__ import annotations

import pytest
from constellation_node_sdk.transport.packet import create_transport_packet
from constellation_node_sdk.transport.provenance import RoutingProvenance

from constellation_gate.boundary.ingress_validator import (
    IngressAuthorizationError,
    IngressValidationError,
    IngressValidator,
)


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


# ── Caller policy (L9_KEY_ALLOWED_ACTIONS_JSON) ──────────────────────────────

_KEYS = {
    "odoo-k1": "odoo-secret-0123456789",
    "eie-k1": "eie-secret-0123456789",
    "graph-k1": "graph-secret-0123456789",
}


def _policy(
    *,
    node: str = "odoo",
    kind: str = "consumer",
    tenants: tuple[str, ...] = ("tenant-a",),
    actions: tuple[str, ...] = ("converge", "match"),
):
    from constellation_gate.config.settings import CallerPolicy

    return CallerPolicy(node=node, kind=kind, tenants=tenants, actions=actions)


def _signed(
    action: str,
    key_id: str,
    *,
    source_node: str = "odoo",
    tenant: str = "tenant-a",
) -> dict:
    from constellation_node_sdk.security.signing import sign_transport_packet

    packet = create_transport_packet(
        action=action,
        payload={"entity_id": "42"},
        tenant=tenant,
        destination_node="gate",
        source_node=source_node,
        reply_to=source_node,
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
        caller_policies={"odoo-k1": _policy()},
    )


@pytest.mark.parametrize("action", ["converge", "match"])
def test_scoped_key_may_invoke_its_listed_actions(action: str) -> None:
    validated = _scoped_validator().validate(_signed(action, "odoo-k1"))

    assert validated.header.action == action


def test_scoped_key_is_refused_an_action_outside_its_scope() -> None:
    from constellation_gate.boundary.ingress_validator import IngressAuthorizationError

    with pytest.raises(IngressAuthorizationError, match="'odoo-k1'.*'sync'"):
        _scoped_validator().validate(_signed("sync", "odoo-k1"))


def test_odoo_consumer_sync_is_refused() -> None:
    """O_G1: an admitted consumer key cannot invoke the graph write action."""
    with pytest.raises(IngressAuthorizationError, match="'odoo-k1'.*'sync'"):
        _scoped_validator().validate(_signed("sync", "odoo-k1"))


def test_odoo_consumer_cannot_claim_another_node() -> None:
    """O_G2: the Odoo key cannot present itself as enrichment-engine."""
    with pytest.raises(IngressAuthorizationError, match="source_node 'enrichment-engine'"):
        _scoped_validator().validate(
            _signed("converge", "odoo-k1", source_node="enrichment-engine")
        )


def test_odoo_consumer_cannot_act_for_another_tenant() -> None:
    """O_G3: the Odoo key cannot act for a tenant outside its record."""
    with pytest.raises(IngressAuthorizationError, match="tenant 'some-other-tenant'"):
        _scoped_validator().validate(_signed("match", "odoo-k1", tenant="some-other-tenant"))


def test_key_missing_from_a_configured_policy_is_refused() -> None:
    with pytest.raises(IngressAuthorizationError, match="no caller policy"):
        _scoped_validator().validate(_signed("sync", "eie-k1", source_node="enrichment-engine"))


def test_worker_key_with_sync_in_its_policy_may_invoke_sync() -> None:
    validator = IngressValidator(
        local_node="gate",
        require_signature=True,
        key_resolver=_KEYS.get,
        caller_policies={
            "graph-k1": _policy(
                node="graph",
                kind="worker",
                actions=("sync", "match"),
            )
        },
    )

    validated = validator.validate(_signed("sync", "graph-k1", source_node="graph"))

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


def test_unsigned_packet_is_refused_when_scopes_are_configured() -> None:
    from constellation_gate.boundary.ingress_validator import IngressAuthorizationError

    # Signatures not mandatory (e.g. network trust mode): omitting the signature
    # must not be a way around the caller's scope.
    validator = IngressValidator(
        local_node="gate",
        require_signature=False,
        key_resolver=_KEYS.get,
        caller_policies={"odoo-k1": _policy()},
    )
    packet = create_transport_packet(
        action="sync",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="odoo",
        reply_to="odoo",
    )

    with pytest.raises(IngressAuthorizationError, match="unsigned"):
        validator.validate(packet.model_dump_json_dict())
