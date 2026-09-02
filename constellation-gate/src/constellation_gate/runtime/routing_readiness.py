"""Routing readiness: can Gate route a canonical action right now? (ADR-GATE-014)

"The Gate process is up" is a weaker claim than "Gate can route converge to a
healthy EIE". Liveness answers the first; only this check answers the second,
and only the second is a safe precondition for a canary.

This is a read of live registry state. It deliberately performs no network I/O:
it reports whether routing WOULD resolve, so it is cheap enough to call on a
readiness path without amplifying load onto workers.
"""

from __future__ import annotations

from typing import Any

from constellation_gate.routing.action_ownership import (
    SEAM_ACTIONS,
    normalize_owner,
    owner_for_registration,
    required_owner_for_action,
)
from constellation_gate.routing.node_registry import NodeRegistry

# The canonical rails that must be routable before a Gate canary: the complete
# bidirectional EIE <-> CEG seam (seam audit 2026-09-02). A Gate that can route
# `converge` to EIE but cannot route `sync` to CEG is not ready for the seam --
# EIE's post-enrichment side effects would fail closed on every request.
DEFAULT_REQUIRED_ACTIONS: tuple[str, ...] = SEAM_ACTIONS


def action_routability(registry: NodeRegistry, action: str) -> dict[str, Any]:
    """Report whether ``action`` resolves to a healthy, correctly-owned worker."""
    normalized_action = action.strip().lower()
    required_owner = required_owner_for_action(normalized_action)

    advertising: list[str] = []
    healthy_advertising: list[str] = []
    owners: dict[str, str | None] = {}

    # snapshot(), not resolve_destination(): resolution hides unhealthy nodes,
    # and "registered but unhealthy" must not be reported as "never registered".
    # Those are different operational problems with different fixes.
    for node_name, registration in sorted(registry.snapshot().items()):
        if normalized_action not in registration.supported_actions:
            continue
        advertising.append(node_name)
        owners[node_name] = owner_for_registration(
            node_name=node_name, metadata=dict(registration.metadata)
        )
        if registration.healthy:
            healthy_advertising.append(node_name)

    resolved_node: str | None = None
    resolution_error: str | None = None
    try:
        resolved_node = registry.resolve_action(normalized_action).node_name
    except (LookupError, ValueError) as exc:
        resolution_error = str(exc)

    owner_ok = True
    owner_problem: str | None = None
    if required_owner is not None:
        if resolved_node is None:
            owner_ok = False
            owner_problem = f"no healthy node resolves {normalized_action!r}"
        else:
            resolved_owner = owners.get(resolved_node)
            if normalize_owner(resolved_owner, allow_unknown=True) != required_owner:
                owner_ok = False
                owner_problem = (
                    f"{normalized_action!r} resolved to node {resolved_node!r} with owner "
                    f"{resolved_owner!r}; canonical owner is {required_owner!r}"
                )

    routable = resolved_node is not None and owner_ok

    return {
        "action": normalized_action,
        "routable": routable,
        "required_owner": required_owner,
        "resolved_node": resolved_node,
        "advertising_nodes": advertising,
        "healthy_advertising_nodes": healthy_advertising,
        "owners": owners,
        "problem": owner_problem or resolution_error,
    }


def routing_readiness(
    registry: NodeRegistry,
    *,
    required_actions: tuple[str, ...] = DEFAULT_REQUIRED_ACTIONS,
) -> dict[str, Any]:
    """Aggregate readiness across every action that must be routable."""
    actions = [action_routability(registry, action) for action in required_actions]
    blocking = [entry for entry in actions if not entry["routable"]]

    return {
        "ready": not blocking,
        "status": "ready" if not blocking else "not_ready",
        "required_actions": list(required_actions),
        "actions": actions,
        "problems": [entry["problem"] for entry in blocking if entry["problem"]],
    }
