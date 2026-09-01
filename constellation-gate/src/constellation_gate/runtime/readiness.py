"""Routability readiness, distinct from liveness.

``/v1/health`` answers "is this process up?". Operators and orchestrators rely
on that as a liveness probe and it must keep its meaning -- redefining it to
include downstream state would take Gate out of rotation whenever a worker
blips, which is exactly backwards.

Readiness answers a different question, the one that actually matters before a
canary: *can Gate route this action right now?* A Gate that is up but has no
registered, correctly-owned, healthy node for ``converge`` is live and
un-routable, and only a readiness probe can say so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from constellation_gate.routing.action_ownership import (
    owner_for_registration,
    required_owner_for_action,
)
from constellation_gate.routing.node_registry import NodeRegistry


@dataclass(frozen=True)
class ActionReadiness:
    action: str
    routable: bool
    required_owner: str | None
    resolved_node: str | None
    resolved_owner: str | None
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "routable": self.routable,
            "required_owner": self.required_owner,
            "resolved_node": self.resolved_node,
            "resolved_owner": self.resolved_owner,
            "reasons": list(self.reasons),
        }


def check_action_routable(registry: NodeRegistry, action: str) -> ActionReadiness:
    """Resolve ``action`` exactly as dispatch would, and report why if it cannot.

    Deliberately uses ``registry.resolve_action`` -- the same call the resolver
    makes -- so readiness cannot drift from real routing behavior.
    """
    normalized = action.strip().lower()
    required_owner = required_owner_for_action(normalized)
    reasons: list[str] = []

    try:
        registration = registry.resolve_action(normalized)
    except (LookupError, ValueError) as exc:
        return ActionReadiness(
            action=normalized,
            routable=False,
            required_owner=required_owner,
            resolved_node=None,
            resolved_owner=None,
            reasons=(str(exc),),
        )

    resolved_owner = owner_for_registration(
        node_name=registration.node_name,
        metadata=dict(registration.metadata),
    )

    if required_owner is not None and resolved_owner != required_owner:
        reasons.append(
            f"action {normalized!r} resolved to node {registration.node_name!r} "
            f"with owner {resolved_owner!r}; canonical owner is {required_owner!r}"
        )

    if not registration.healthy:
        reasons.append(f"node {registration.node_name!r} is not healthy")

    return ActionReadiness(
        action=normalized,
        routable=not reasons,
        required_owner=required_owner,
        resolved_node=registration.node_name,
        resolved_owner=resolved_owner,
        reasons=tuple(reasons),
    )


def readiness_report(
    registry: NodeRegistry,
    *,
    required_actions: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Readiness for every ``required_actions`` entry.

    With no required actions the report is ``ready`` -- an operator who has
    declared no routing requirement has none to fail.
    """
    checks = [check_action_routable(registry, action) for action in required_actions]
    return {
        "ready": all(check.routable for check in checks),
        "registered_nodes": sorted(registry.known_nodes()),
        "actions": [check.as_dict() for check in checks],
    }
