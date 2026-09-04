"""GET /v1/ready is a routability probe, distinct from /v1/health liveness."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from constellation_gate.api import dependencies as deps
from constellation_gate.api.main import create_app
from constellation_gate.routing.node_registry import NodeRegistration


@pytest.fixture
def client_and_registry():
    deps.get_registry.cache_clear()
    registry = deps.get_registry()
    yield TestClient(create_app()), registry
    deps.get_registry.cache_clear()


def _eie(*, healthy: bool = True) -> NodeRegistration:
    """The exact shape EIE registers (app/main.py ADVERTISED_ACTIONS)."""
    return NodeRegistration(
        node_name="enrichment-engine",
        internal_url="http://enrichment-engine:8000",
        supported_actions=("converge", "graph-inference-result", "enrich", "enrich-and-sync"),
        health_endpoint="/api/v1/health",
        metadata={"owner": "eie"},
        healthy=healthy,
    )


def _ceg(*, healthy: bool = True) -> NodeRegistration:
    """The exact shape CEG registers (engine/spec.yaml)."""
    return NodeRegistration(
        node_name="graph",
        internal_url="http://graph:8000",
        supported_actions=("match", "sync", "outcomes", "resolve"),
        health_endpoint="/v1/health",
        metadata={"owner": "ceg"},
        healthy=healthy,
    )


def test_ready_returns_503_when_converge_is_not_routable(client_and_registry) -> None:
    client, _ = client_and_registry
    response = client.get("/v1/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["ready"] is False
    assert body["problems"]


def test_ready_returns_503_with_only_one_side_of_the_seam(client_and_registry) -> None:
    """EIE alone routes converge; the seam also needs CEG for sync/match/outcomes."""
    client, registry = client_and_registry
    registry.register_node("enrichment-engine", _eie())

    response = client.get("/v1/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["ready"] is False
    not_routable = {a["action"] for a in body["actions"] if not a["routable"]}
    assert not_routable == {"match", "sync", "outcomes"}


def test_ready_returns_200_once_both_seam_nodes_are_registered_and_healthy(
    client_and_registry,
) -> None:
    client, registry = client_and_registry
    registry.register_node("enrichment-engine", _eie())
    registry.register_node("graph", _ceg())

    response = client.get("/v1/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    resolved = {a["action"]: a["resolved_node"] for a in body["actions"]}
    assert resolved["converge"] == "enrichment-engine"
    assert resolved["sync"] == "graph"


def test_ready_returns_503_when_the_owner_is_registered_but_unhealthy(
    client_and_registry,
) -> None:
    client, registry = client_and_registry
    registry.register_node("enrichment-engine", _eie(healthy=False))
    registry.register_node("graph", _ceg())

    response = client.get("/v1/ready")
    assert response.status_code == 503
    # "registered but unhealthy" and "never registered" are different problems.
    converge = next(a for a in response.json()["actions"] if a["action"] == "converge")
    assert converge["advertising_nodes"] == ["enrichment-engine"]
    assert converge["healthy_advertising_nodes"] == []


def test_health_stays_a_pure_liveness_probe(client_and_registry) -> None:
    """Health must NOT go red because a worker is missing.

    Folding routability into liveness would pull Gate out of rotation whenever a
    downstream blips -- the opposite of what a liveness probe is for.
    """
    client, _ = client_and_registry
    response = client.get("/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
