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
