from __future__ import annotations

import pytest

from constellation_gate.boundary.ingress_validator import IngressValidationError, IngressValidator
from constellation_gate.boundary.routing_policy import RoutingPolicyError, validate_gate_dispatch_policy
from constellation_node_sdk.transport.packet import create_transport_packet
from constellation_node_sdk.transport.provenance import RoutingProvenance


def test_architecture_rejects_direct_node_to_node_packet_at_gate_ingress() -> None:
    validator = IngressValidator(
        local_node="gate",
        known_nodes_provider=lambda: {"orchestrator", "score", "enrich"},
    )

    illegal_packet = create_transport_packet(
        action="score",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="score",
        source_node="orchestrator",
        reply_to="orchestrator",
        provenance=RoutingProvenance(
            origin_kind="node",
            requested_action="score",
            resolved_by_gate=False,
            original_source_node="orchestrator",
        ),
    )

    with pytest.raises(IngressValidationError):
        validator.validate(illegal_packet.model_dump_json_dict())


def test_architecture_allows_node_to_gate_then_gate_to_worker_split() -> None:
    validator = IngressValidator(
        local_node="gate",
        known_nodes_provider=lambda: {"orchestrator", "score", "enrich"},
    )

    node_to_gate_packet = create_transport_packet(
        action="score",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="orchestrator",
        reply_to="orchestrator",
        provenance=RoutingProvenance(
            origin_kind="node",
            requested_action="score",
            resolved_by_gate=False,
            original_source_node="orchestrator",
        ),
    )

    validated = validator.validate(node_to_gate_packet.model_dump_json_dict())
    assert validated.address.destination_node == "gate"

    gate_dispatch_packet = create_transport_packet(
        action="score",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="score",
        source_node="gate",
        reply_to="gate",
        provenance=RoutingProvenance(
            origin_kind="gate",
            requested_action="score",
            resolved_by_gate=True,
            original_source_node="orchestrator",
        ),
    )

    validate_gate_dispatch_policy(gate_dispatch_packet, local_node="gate")


def test_architecture_rejects_non_gate_origin_for_direct_worker_dispatch() -> None:
    illegal_dispatch = create_transport_packet(
        action="score",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="score",
        source_node="orchestrator",
        reply_to="orchestrator",
        provenance=RoutingProvenance(
            origin_kind="node",
            requested_action="score",
            resolved_by_gate=True,
            original_source_node="orchestrator",
        ),
    )

    with pytest.raises(RoutingPolicyError):
        validate_gate_dispatch_policy(illegal_dispatch, local_node="gate")
