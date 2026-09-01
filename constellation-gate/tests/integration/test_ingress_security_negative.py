"""Adversarial ingress: every rejection path Gate must fail closed on.

These are negative tests on purpose. A validator that has only ever been shown
well-formed packets is untested; the interesting question is what it refuses.
"""

from __future__ import annotations

from typing import Any

import pytest
from constellation_node_sdk.transport.packet import TransportPacket, create_transport_packet
from constellation_node_sdk.transport.provenance import RoutingProvenance

from constellation_gate.boundary.ingress_validator import IngressValidationError, IngressValidator
from constellation_gate.boundary.routing_policy import (
    RoutingPolicyError,
    validate_gate_dispatch_policy,
)
from constellation_gate.resilience.replay_guard import ReplayDetectedError, ReplayGuard
from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry

GATE = "gate"


def _validator(**overrides: Any) -> IngressValidator:
    kwargs: dict[str, Any] = {"local_node": GATE, "dev_mode": True}
    kwargs.update(overrides)
    return IngressValidator(**kwargs)


def _client_packet(**overrides: Any) -> TransportPacket:
    kwargs: dict[str, Any] = {
        "action": "score",
        "payload": {"a": 1},
        "tenant": "tenant-a",
        "destination_node": GATE,
        "source_node": "client",
        "reply_to": "client",
    }
    kwargs.update(overrides)
    return create_transport_packet(**kwargs)


def test_tampered_payload_is_rejected() -> None:
    """Changing the payload after hashing must not validate."""
    body = _client_packet().model_dump_json_dict()
    body["payload"]["a"] = 999

    with pytest.raises(IngressValidationError):
        _validator().validate(body)


def test_tampered_transport_metadata_is_rejected() -> None:
    body = _client_packet().model_dump_json_dict()
    body["address"]["destination_node"] = "somewhere-else"

    with pytest.raises(IngressValidationError):
        _validator().validate(body)


def test_tampered_transport_hash_is_rejected() -> None:
    body = _client_packet().model_dump_json_dict()
    body["security"]["transport_hash"] = "0" * 64

    with pytest.raises(IngressValidationError):
        _validator().validate(body)


def test_missing_signature_is_rejected_when_signatures_are_required() -> None:
    body = _client_packet().model_dump_json_dict()

    with pytest.raises(IngressValidationError):
        _validator(require_signature=True, dev_mode=False).validate(body)


def test_unknown_signing_key_is_rejected() -> None:
    body = _client_packet().model_dump_json_dict()
    body["security"]["signature"] = "not-a-real-signature"
    body["security"]["signature_algorithm"] = "hmac-sha256"
    body["security"]["signing_key_id"] = "key-nobody-knows"

    with pytest.raises(IngressValidationError):
        _validator(
            require_signature=True,
            dev_mode=False,
            key_resolver=lambda key_id: None,
        ).validate(body)


def test_node_originated_packet_may_not_target_a_peer_directly() -> None:
    """The whole point of Gate: nodes re-enter, they never call peers."""
    body = _client_packet(
        source_node="orchestrator",
        destination_node="score",
        reply_to="orchestrator",
        provenance=RoutingProvenance(
            origin_kind="node",
            requested_action="score",
            resolved_by_gate=False,
            original_source_node="orchestrator",
        ),
    ).model_dump_json_dict()

    # Rejected by the SDK's local-node check before Gate's own routing policy
    # even runs; either layer refusing is the contract being asserted.
    with pytest.raises(IngressValidationError, match="destination"):
        _validator().validate(body)


def test_node_packet_may_not_misdeclare_its_original_source() -> None:
    body = _client_packet(
        source_node="orchestrator",
        destination_node=GATE,
        reply_to="orchestrator",
        provenance=RoutingProvenance(
            origin_kind="node",
            requested_action="score",
            resolved_by_gate=False,
            original_source_node="someone-else",
        ),
    ).model_dump_json_dict()

    with pytest.raises(IngressValidationError):
        _validator().validate(body)


def test_action_outside_the_allow_list_is_rejected() -> None:
    body = _client_packet(action="score").model_dump_json_dict()

    with pytest.raises(IngressValidationError):
        _validator(allowed_actions=("converge",)).validate(body)


def test_oversized_packet_is_rejected() -> None:
    body = _client_packet(payload={"blob": "x" * 5000}).model_dump_json_dict()

    with pytest.raises(IngressValidationError):
        _validator(max_packet_bytes=1024).validate(body)


def test_a_caller_may_not_forge_a_gate_authored_dispatch_packet() -> None:
    """origin_kind='gate' from an outside caller must not be honored."""
    forged = _client_packet(
        source_node="attacker",
        destination_node="score",
        reply_to="attacker",
        provenance=RoutingProvenance(
            origin_kind="gate",
            requested_action="score",
            resolved_by_gate=True,
            original_source_node="attacker",
        ),
    )

    with pytest.raises(RoutingPolicyError, match="source_node must equal local Gate node"):
        validate_gate_dispatch_policy(forged, local_node=GATE)


def test_a_dispatch_packet_must_be_gate_authored() -> None:
    node_authored = _client_packet(
        source_node=GATE,
        destination_node="score",
        reply_to=GATE,
        provenance=RoutingProvenance(
            origin_kind="node",
            requested_action="score",
            resolved_by_gate=True,
            original_source_node=GATE,
        ),
    )

    with pytest.raises(RoutingPolicyError, match="origin_kind='gate'"):
        validate_gate_dispatch_policy(node_authored, local_node=GATE)


def test_a_dispatch_packet_must_declare_gate_resolution() -> None:
    unresolved = _client_packet(
        source_node=GATE,
        destination_node="score",
        reply_to=GATE,
        provenance=RoutingProvenance(
            origin_kind="gate",
            requested_action="score",
            resolved_by_gate=False,
            original_source_node="client",
        ),
    )

    with pytest.raises(RoutingPolicyError, match="resolved_by_gate=true"):
        validate_gate_dispatch_policy(unresolved, local_node=GATE)


def test_replayed_packet_id_is_rejected_inside_the_window() -> None:
    guard = ReplayGuard(window_seconds=300)
    packet = _client_packet()

    guard.check_and_record(str(packet.header.packet_id))
    with pytest.raises(ReplayDetectedError):
        guard.check_and_record(str(packet.header.packet_id))


def test_registration_owner_collision_is_rejected() -> None:
    from constellation_gate.routing.action_ownership import ActionOwnershipError

    registry = NodeRegistry()
    with pytest.raises(ActionOwnershipError):
        registry.register_node(
            "impostor",
            NodeRegistration(
                node_name="impostor",
                internal_url="http://impostor:8000",
                supported_actions=("converge",),
                metadata={"owner": "ceg"},
            ),
        )
