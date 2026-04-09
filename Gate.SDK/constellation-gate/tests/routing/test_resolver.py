from __future__ import annotations

import pytest

from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry
from constellation_gate.routing.resolver import RouteResolver
from constellation_node_sdk.transport.packet import create_transport_packet
from constellation_node_sdk.transport.provenance import RoutingProvenance


def _build_registry() -> NodeRegistry:
    registry = NodeRegistry()
    registry.register_node(
        "enrich",
        NodeRegistration(
            node_name="enrich",
            internal_url="http://enrich:8000",
            supported_actions=("enrich",),
        ),
    )
    registry.register_node(
        "score",
        NodeRegistration(
            node_name="score",
            internal_url="http://score:8000",
            supported_actions=("score",),
        ),
    )
    return registry


def test_resolver_resolves_gate_bound_packet_by_action() -> None:
    resolver = RouteResolver(_build_registry(), local_node="gate")

    packet = create_transport_packet(
        action="enrich",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )

    resolved = resolver.resolve(packet)
    assert resolved.node_name == "enrich"


def test_resolver_resolves_gate_authored_dispatch_by_destination() -> None:
    resolver = RouteResolver(_build_registry(), local_node="gate")

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

    resolved = resolver.resolve(packet)
    assert resolved.node_name == "score"


def test_resolver_rejects_non_gate_origin_for_worker_target() -> None:
    resolver = RouteResolver(_build_registry(), local_node="gate")

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
            resolved_by_gate=False,
            original_source_node="orchestrator",
        ),
    )

    with pytest.raises(LookupError):
        resolver.resolve(packet)
