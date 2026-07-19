from __future__ import annotations

import pytest
from constellation_node_sdk.transport.packet import create_transport_packet
from constellation_node_sdk.transport.provenance import RoutingProvenance

from constellation_gate.boundary.routing_policy import (
    RoutingPolicyError,
    validate_gate_dispatch_policy,
    validate_node_origin_policy,
)


def test_validate_node_origin_policy_accepts_registered_node_targeting_gate() -> None:
    packet = create_transport_packet(
        action="enrich",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="orchestrator",
        reply_to="orchestrator",
        provenance=RoutingProvenance(
            origin_kind="node",
            requested_action="enrich",
            resolved_by_gate=False,
            original_source_node="orchestrator",
        ),
    )

    validate_node_origin_policy(
        packet,
        local_node="gate",
        known_nodes={"orchestrator", "enrich"},
    )


def test_validate_node_origin_policy_rejects_direct_node_to_node_target() -> None:
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

    with pytest.raises(RoutingPolicyError):
        validate_node_origin_policy(
            packet,
            local_node="gate",
            known_nodes={"orchestrator", "enrich"},
        )


def test_validate_gate_dispatch_policy_accepts_gate_authored_worker_dispatch() -> None:
    packet = create_transport_packet(
        action="enrich",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="enrich",
        source_node="gate",
        reply_to="gate",
        provenance=RoutingProvenance(
            origin_kind="gate",
            requested_action="enrich",
            resolved_by_gate=True,
            original_source_node="orchestrator",
        ),
    )

    validate_gate_dispatch_policy(packet, local_node="gate")
