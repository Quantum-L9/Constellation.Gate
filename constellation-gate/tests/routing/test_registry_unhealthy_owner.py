"""A known action whose owner is unhealthy is a 503, not a 404.

Both cases used to raise the same LookupError ("no healthy node registered"),
so a worker that had merely blipped presented to callers exactly like an
action Gate never routes -- and callers classify 404 as permanent.
"""

from __future__ import annotations

import pytest

from constellation_gate.api.errors import to_http_exception
from constellation_gate.routing.node_registry import (
    NodeRegistration,
    NodeRegistry,
    NoHealthyNodeError,
)


def _registry() -> NodeRegistry:
    registry = NodeRegistry()
    registry.register_node(
        "enrichment-engine",
        NodeRegistration(
            node_name="enrichment-engine",
            internal_url="http://enrichment-engine:8000",
            supported_actions=("converge",),
            metadata={"owner": "eie"},
        ),
    )
    return registry


def test_unhealthy_owner_is_a_distinct_transient_error() -> None:
    registry = _registry()
    registry.mark_unhealthy("enrichment-engine")
    with pytest.raises(NoHealthyNodeError, match="unhealthy"):
        registry.resolve_action("converge")
    # Still a LookupError for callers that only know the generic case.
    with pytest.raises(LookupError):
        registry.resolve_action("converge")


def test_unknown_action_is_still_not_found() -> None:
    registry = _registry()
    with pytest.raises(LookupError, match="no node registered") as excinfo:
        registry.resolve_action("no-such-action")
    assert not isinstance(excinfo.value, NoHealthyNodeError)


def test_http_mapping_503_for_unhealthy_owner_and_404_for_unknown() -> None:
    registry = _registry()
    registry.mark_unhealthy("enrichment-engine")
    try:
        registry.resolve_action("converge")
    except LookupError as exc:
        unhealthy = to_http_exception(exc)
    try:
        registry.resolve_action("no-such-action")
    except LookupError as exc:
        unknown = to_http_exception(exc)
    assert unhealthy.status_code == 503
    assert unhealthy.detail["code"] == "no_healthy_node"
    assert unknown.status_code == 404
    assert unknown.detail["code"] == "not_found"


def test_recovery_restores_resolution() -> None:
    registry = _registry()
    registry.mark_unhealthy("enrichment-engine")
    registry.mark_healthy("enrichment-engine")
    assert registry.resolve_action("converge").node_name == "enrichment-engine"
