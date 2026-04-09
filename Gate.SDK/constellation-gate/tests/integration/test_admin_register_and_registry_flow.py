from __future__ import annotations

from fastapi.testclient import TestClient

from constellation_gate.api import dependencies as deps
from constellation_gate.api.main import create_app
from constellation_gate.routing.node_registry import NodeRegistry
from constellation_gate.services.admin_registration_service import AdminRegistrationService
from constellation_gate.services.registry_query_service import RegistryQueryService


def test_admin_register_then_registry_snapshot_flow() -> None:
    app = create_app()
    registry = NodeRegistry()
    admin_service = AdminRegistrationService(registry, admin_token="secret")
    registry_service = RegistryQueryService(registry)

    original_admin = deps.get_admin_registration_service
    original_registry = deps.get_registry_query_service
    deps.get_admin_registration_service = lambda: admin_service
    deps.get_registry_query_service = lambda: registry_service
    try:
        client = TestClient(app)

        register_response = client.post(
            "/v1/admin/register?overwrite=true",
            headers={"X-Admin-Token": "secret"},
            json={
                "score": {
                    "internal_url": "http://score:8000",
                    "supported_actions": ["score"],
                    "priority_class": "P1",
                    "max_concurrent": 25,
                    "health_endpoint": "/v1/health",
                    "timeout_ms": 15000,
                    "metadata": {"version": "1.0.0"},
                }
            },
        )

        assert register_response.status_code == 200
        body = register_response.json()
        assert body["total_nodes"] == 1
        assert body["registered"][0]["node_name"] == "score"

        registry_response = client.get("/v1/registry")
        assert registry_response.status_code == 200
        snapshot = registry_response.json()
        assert "score" in snapshot
        assert snapshot["score"]["internal_url"] == "http://score:8000"
        assert snapshot["score"]["supported_actions"] == ["score"]
    finally:
        deps.get_admin_registration_service = original_admin
        deps.get_registry_query_service = original_registry
