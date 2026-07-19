from __future__ import annotations

import pytest
from constellation_node_sdk.transport.packet import create_transport_packet
from constellation_node_sdk.transport.provenance import RoutingProvenance

from constellation_gate.boundary.routing_policy import (
    RoutingPolicyError,
    validate_gate_dispatch_policy,
)


def test_gate_dispatch_authority_accepts_gate_authored_worker_dispatch() -> None:
    packet = create_transport_packet(
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

    validate_gate_dispatch_policy(packet, local_node="gate")


def test_gate_dispatch_authority_rejects_non_gate_authored_worker_dispatch() -> None:
    packet = create_transport_packet(
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
        validate_gate_dispatch_policy(packet, local_node="gate")
