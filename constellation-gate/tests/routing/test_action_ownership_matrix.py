"""Canonical action ownership matrix, checked against the live EIE registration.

Registration is generic: Gate must accept the canonical SDK-shaped payload EIE
actually sends, without Gate learning anything EIE-specific.
"""

from __future__ import annotations

import pytest

from constellation_gate.routing.action_ownership import (
    CANONICAL_ACTION_OWNERS,
    ActionOwnershipError,
    owner_for_registration,
)
from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry

# Verbatim from EIE app/services/gate_registration.py (NODE_NAME,
# SUPPORTED_ACTIONS, HEALTH_ENDPOINT, metadata) as of the audited HEAD.
EIE_NODE_NAME = "enrichment-engine"
EIE_SUPPORTED_ACTIONS = ("converge", "graph-inference-result", "enrich", "enrich-and-sync")
EIE_METADATA = {"owner": "eie", "version": "2.3.0", "type": "enrichment"}
EIE_HEALTH_ENDPOINT = "/api/v1/health"


def _eie() -> NodeRegistration:
    return NodeRegistration(
        node_name=EIE_NODE_NAME,
        internal_url="http://enrichment-engine:8000",
        supported_actions=EIE_SUPPORTED_ACTIONS,
        health_endpoint=EIE_HEALTH_ENDPOINT,
        metadata=dict(EIE_METADATA),
    )


def test_canonical_matrix_is_the_expected_authority_lock() -> None:
    assert CANONICAL_ACTION_OWNERS == {
        "match": "ceg",
        "sync": "ceg",
        "outcomes": "ceg",
        "converge": "eie",
        "graph-inference-result": "eie",
    }


def test_gate_accepts_the_live_eie_registration_payload() -> None:
    registry = NodeRegistry()
    registry.register_node(EIE_NODE_NAME, _eie())

    assert owner_for_registration(node_name=EIE_NODE_NAME, metadata=dict(EIE_METADATA)) == "eie"
    assert registry.resolve_action("converge").node_name == EIE_NODE_NAME


def test_converge_resolves_to_the_eie_owner() -> None:
    registry = NodeRegistry()
    registry.register_node(EIE_NODE_NAME, _eie())
    resolved = registry.resolve_action("converge")
    assert owner_for_registration(
        node_name=resolved.node_name, metadata=dict(resolved.metadata)
    ) == "eie"


def test_a_non_eie_node_may_not_claim_converge() -> None:
    registry = NodeRegistry()
    with pytest.raises(ActionOwnershipError, match="owned by 'eie'"):
        registry.register_node(
            "rogue",
            NodeRegistration(
                node_name="rogue",
                internal_url="http://rogue:8000",
                supported_actions=("converge",),
                metadata={"owner": "ceg"},
            ),
        )


def test_an_unowned_node_may_not_claim_a_canonical_action() -> None:
    registry = NodeRegistry()
    with pytest.raises(ActionOwnershipError, match="requires metadata.owner"):
        registry.register_node(
            "mystery",
            NodeRegistration(
                node_name="mystery",
                internal_url="http://mystery:8000",
                supported_actions=("converge",),
            ),
        )


def test_replicas_of_the_same_owner_are_allowed() -> None:
    """Horizontal scaling is not an ownership collision."""
    registry = NodeRegistry()
    registry.register_node(EIE_NODE_NAME, _eie())
    registry.register_node(
        "enrichment-engine-2",
        NodeRegistration(
            node_name="enrichment-engine-2",
            internal_url="http://enrichment-engine-2:8000",
            supported_actions=("converge",),
            metadata={"owner": "eie"},
        ),
    )
    assert registry.resolve_action("converge").node_name in {
        EIE_NODE_NAME,
        "enrichment-engine-2",
    }


def test_cross_owner_collision_on_a_shared_action_is_rejected() -> None:
    registry = NodeRegistry()
    registry.register_node(
        "node-a",
        NodeRegistration(
            node_name="node-a",
            internal_url="http://a:8000",
            supported_actions=("custom",),
            metadata={"owner": "eie"},
        ),
    )
    with pytest.raises(ActionOwnershipError, match="ownership collision"):
        registry.register_node(
            "node-b",
            NodeRegistration(
                node_name="node-b",
                internal_url="http://b:8000",
                supported_actions=("custom",),
                metadata={"owner": "ceg"},
            ),
        )


def test_registration_schema_stays_generic() -> None:
    """Gate must not grow EIE-specific registration fields."""
    fields = set(NodeRegistration.model_fields)
    assert fields == {
        "node_name",
        "internal_url",
        "supported_actions",
        "priority_class",
        "max_concurrent",
        "health_endpoint",
        "timeout_ms",
        "metadata",
        "healthy",
        "active_requests",
    }
