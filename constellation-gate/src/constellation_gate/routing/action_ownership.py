"""Canonical action ownership for Gate registration.

Authority: TASK-002 approved action registry (PlasticOS path).
One semantic owner per canonical action. Multiple replicas of the same
owner are allowed; cross-owner claims are collisions and must fail closed.
"""

from __future__ import annotations

from typing import Final

# TASK-002 / ACTION_REGISTRY PlasticOS authority lock.
CANONICAL_ACTION_OWNERS: Final[dict[str, str]] = {
    "match": "ceg",
    "sync": "ceg",
    "outcomes": "ceg",
    "converge": "eie",
    "graph-inference-result": "eie",
}

_OWNER_ALIASES: Final[dict[str, str]] = {
    "ceg": "ceg",
    "cognitive": "ceg",
    "cognitive_engine_graphs": "ceg",
    "cognitive-engine-graphs": "ceg",
    "eie": "eie",
    "enrichment": "eie",
    "enrichment_inference_engine": "eie",
    "enrichment-inference-engine": "eie",
}


class ActionOwnershipError(ValueError):
    """Raised when registration violates canonical action ownership."""


def normalize_owner(value: str | None, *, allow_unknown: bool = False) -> str | None:
    if value is None:
        return None
    key = value.strip().lower().replace(" ", "_")
    if not key:
        return None
    if key in _OWNER_ALIASES:
        return _OWNER_ALIASES[key]
    for alias, owner in _OWNER_ALIASES.items():
        if alias in key:
            return owner
    return key if allow_unknown else None


def owner_for_registration(*, node_name: str, metadata: dict[str, str]) -> str | None:
    """Resolve semantic owner from explicit metadata, then node name."""
    if "owner" in metadata and str(metadata.get("owner", "")).strip():
        return normalize_owner(metadata.get("owner"), allow_unknown=True)
    return normalize_owner(node_name, allow_unknown=False)


def required_owner_for_action(action: str) -> str | None:
    return CANONICAL_ACTION_OWNERS.get(action.strip().lower())


def assert_registration_ownership(
    *,
    node_name: str,
    supported_actions: tuple[str, ...],
    metadata: dict[str, str],
    existing: dict[str, tuple[str, ...]],
    existing_owners: dict[str, str | None],
) -> None:
    """Fail closed on canonical owner mismatch or cross-owner action collision.

    ``existing`` maps node_name -> supported_actions for nodes already registered
    (excluding the node currently being overwritten).
    ``existing_owners`` maps node_name -> semantic owner (may be None).
    """
    claimant = owner_for_registration(node_name=node_name, metadata=metadata)
    normalized_node = node_name.strip().lower()

    for action in supported_actions:
        normalized_action = action.strip().lower()
        required = required_owner_for_action(normalized_action)
        if required is not None:
            if claimant is None:
                raise ActionOwnershipError(
                    f"canonical action {normalized_action!r} requires metadata.owner "
                    f"or a recognizable owner node_name (expected {required!r})"
                )
            if claimant != required:
                raise ActionOwnershipError(
                    f"action {normalized_action!r} is owned by {required!r}; "
                    f"registration claims owner {claimant!r}"
                )

        for other_node, other_actions in existing.items():
            if other_node == normalized_node:
                continue
            if normalized_action not in other_actions:
                continue
            other_owner = existing_owners.get(other_node)
            # Non-canonical actions may be multi-replica without owner tags.
            if required is None and (claimant is None or other_owner is None):
                continue
            if claimant is not None and other_owner is not None and claimant != other_owner:
                raise ActionOwnershipError(
                    f"action ownership collision for {normalized_action!r}: "
                    f"node {normalized_node!r} owner={claimant!r} conflicts with "
                    f"node {other_node!r} owner={other_owner!r}"
                )
            if required is not None and other_owner is not None and other_owner != required:
                raise ActionOwnershipError(
                    f"action ownership collision for {normalized_action!r}: "
                    f"existing node {other_node!r} owner={other_owner!r} is not "
                    f"canonical owner {required!r}"
                )
