"""Topology-negative and authorization tests for sanitized capability API."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from constellation_gate.api import dependencies as deps
from constellation_gate.api.main import create_app
from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry
from constellation_gate.schemas.capabilities import CapabilityDescriptor
from constellation_gate.services.admin_registration_service import AdminRegistrationService
from constellation_gate.services.capability_service import CapabilityService
from constellation_gate.services.registry_query_service import RegistryQueryService


def _clear_dep_caches() -> None:
    deps.get_registry.cache_clear()
    deps.get_gate_settings.cache_clear()
    deps.get_capability_service.cache_clear()
    deps.get_admin_registration_service.cache_clear()
    deps.get_registry_query_service.cache_clear()


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "score", "internal_url": "http://secret:8000"},
        {"action": "score", "healthy": True},
        {"action": "score", "active_requests": 3},
        {"action": "score", "node_name": "score"},
        {"action": "score", "nested": {"internal_url": "http://x"}},
        {"action": "score", "credentials": "x"},
        {"action": "score", "topology": {}},
    ],
)
def test_capability_descriptor_rejects_forbidden_fields(payload: dict) -> None:
    with pytest.raises(ValidationError):
        CapabilityDescriptor.model_validate(payload)


def test_registry_snapshot_cannot_validate_as_capability_descriptor() -> None:
    registry = NodeRegistry()
    registry.register_node(
        "score",
        NodeRegistration(
            node_name="score",
            internal_url="http://score:8000",
            supported_actions=("score",),
        ),
    )
    raw = RegistryQueryService(registry).snapshot()["score"]
    with pytest.raises(ValidationError):
        CapabilityDescriptor.model_validate(raw)


def test_protected_action_requires_authorization() -> None:
    registry = NodeRegistry()
    service = CapabilityService(registry, admin_token="secret")
    with pytest.raises(PermissionError):
        service.get_capability("match", presented_token=None)
    descriptor, _etag = service.get_capability("match", presented_token="secret")
    assert descriptor.action == "match"
    assert descriptor.owner == "ceg"


def test_etag_changes_after_registration() -> None:
    registry = NodeRegistry()
    service = CapabilityService(registry, admin_token=None)
    before = service.list_capabilities(presented_token=None).etag
    registry.register_node(
        "score",
        NodeRegistration(
            node_name="score",
            internal_url="http://score:8000",
            supported_actions=("score",),
        ),
    )
    after = service.list_capabilities(presented_token=None).etag
    assert before != after


def test_capabilities_endpoints_and_304() -> None:
    _clear_dep_caches()
    registry = NodeRegistry()
    registry.register_node(
        "score",
        NodeRegistration(
            node_name="score",
            internal_url="http://score:8000",
            supported_actions=("score",),
        ),
    )
    cap = CapabilityService(registry, admin_token="secret")
    admin = AdminRegistrationService(registry, admin_token="secret")

    original_cap = deps.get_capability_service
    original_admin = deps.get_admin_registration_service
    deps.get_capability_service = lambda: cap
    deps.get_admin_registration_service = lambda: admin
    try:
        app = create_app()
        with TestClient(app) as client:
            listed = client.get("/v1/capabilities")
            assert listed.status_code == 200
            body = listed.json()
            assert "etag" in body
            assert all("internal_url" not in item for item in body["capabilities"])
            assert all(item["action"] != "match" for item in body["capabilities"])

            cached = client.get("/v1/capabilities", headers={"If-None-Match": body["etag"]})
            assert cached.status_code == 304

            denied = client.get("/v1/capabilities/match")
            assert denied.status_code == 401

            allowed = client.get("/v1/capabilities/match", headers={"X-Admin-Token": "secret"})
            assert allowed.status_code == 200
            assert allowed.json()["owner"] == "ceg"
            assert "internal_url" not in allowed.json()
    finally:
        deps.get_capability_service = original_cap
        deps.get_admin_registration_service = original_admin
        _clear_dep_caches()
