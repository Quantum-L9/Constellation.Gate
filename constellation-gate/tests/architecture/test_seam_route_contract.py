"""EIE <-> CEG seam route contract (seam audit 2026-09-02).

Gate is the only routing authority between Enrichment.Inference.Engine and
Cognitive.Engine.Graphs. This guard pins the route/ownership contract the two
nodes register against, so a change on either side that would silently make a
seam action unroutable -- or routable to the wrong owner -- fails here.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from constellation_gate.resilience.replay_safety import (
    GATE_REPLAY_SAFE_ACTIONS,
    WORKER_OWNED_RETRY_ACTIONS,
)
from constellation_gate.routing.action_ownership import (
    CANONICAL_ACTION_OWNERS,
    SEAM_ACTIONS,
    normalize_owner,
)
from constellation_gate.routing.node_registry import NodeRegistry
from constellation_gate.runtime.routing_readiness import DEFAULT_REQUIRED_ACTIONS, routing_readiness

SRC = Path(__file__).resolve().parents[2] / "src" / "constellation_gate"
STATIC_REGISTRY = SRC / "config" / "node_registry.yaml"

# What each node actually invokes on the other, from exact-head code:
#   EIE  -> Gate -> CEG : app/engines/graph_sync_client.py, app/engines/packet_router.py
#   CEG  -> Gate -> EIE : engine/gate_egress.py
EIE_INVOKES_ON_CEG = ("sync", "match", "outcomes")
CEG_INVOKES_ON_EIE = ("enrich",)
EIE_INBOUND = ("converge", "graph-inference-result", "enrich", "enrich-and-sync")
CEG_INBOUND = ("match", "sync", "outcomes")


def test_every_seam_action_has_exactly_one_canonical_owner() -> None:
    for action in SEAM_ACTIONS:
        assert action in CANONICAL_ACTION_OWNERS, f"{action!r} has no canonical owner"
    for action in EIE_INBOUND:
        assert CANONICAL_ACTION_OWNERS[action] == "eie"
    for action in CEG_INBOUND:
        assert CANONICAL_ACTION_OWNERS[action] == "ceg"


def test_invoked_actions_are_owned_by_the_intended_destination() -> None:
    for action in EIE_INVOKES_ON_CEG:
        assert CANONICAL_ACTION_OWNERS[action] == "ceg"
    for action in CEG_INVOKES_ON_EIE:
        assert CANONICAL_ACTION_OWNERS[action] == "eie"


def test_readiness_covers_the_whole_seam() -> None:
    assert set(SEAM_ACTIONS) <= set(DEFAULT_REQUIRED_ACTIONS)


def test_runtime_node_identities_resolve_to_their_owners() -> None:
    """Node names the two runtimes actually register under (not aliases in docs)."""
    assert normalize_owner("enrichment-engine") == "eie"
    assert normalize_owner("graph") == "ceg"
    assert normalize_owner("graph-engine") == "ceg"


def test_no_seam_action_is_gate_replay_safe() -> None:
    """Retry ownership stays with the domain nodes (ADR-GATE-007/016)."""
    assert not (set(SEAM_ACTIONS) & GATE_REPLAY_SAFE_ACTIONS)
    assert set(SEAM_ACTIONS) <= WORKER_OWNED_RETRY_ACTIONS


def test_static_registry_matches_the_runtime_identities_and_is_seam_ready() -> None:
    raw = yaml.safe_load(STATIC_REGISTRY.read_text(encoding="utf-8"))
    assert set(raw) == {"enrichment-engine", "graph"}
    assert raw["enrichment-engine"]["metadata"]["owner"] == "eie"
    assert raw["graph"]["metadata"]["owner"] == "ceg"
    assert set(raw["enrichment-engine"]["supported_actions"]) == set(EIE_INBOUND)
    assert set(raw["graph"]["supported_actions"]) >= set(CEG_INBOUND)
    assert "enrich" not in raw["graph"]["supported_actions"]

    registry = NodeRegistry()
    registry.load_from_yaml(str(STATIC_REGISTRY))
    report = routing_readiness(registry)
    assert report["ready"] is True, report["problems"]
