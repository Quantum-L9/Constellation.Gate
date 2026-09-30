from __future__ import annotations

from fastapi.testclient import TestClient

from constellation_gate.api import dependencies as deps
from constellation_gate.api.main import create_app


class FakeRegistryQueryService:
    def snapshot(self) -> dict[str, dict]:
        return {
            "enrich": {
                "node_name": "enrich",
                "internal_url": "http://enrich:8000",
                "supported_actions": ["enrich"],
                "healthy": True,
                "active_requests": 0,
            }
        }


_TOKEN = "registry-admin-token"


def _settings_with_token():
    from constellation_gate.config.settings import GateSettings

    return GateSettings(environment="local", local_node="gate", admin_token=_TOKEN)


def test_registry_without_admin_token_returns_no_worker_url() -> None:
    """O_G4: an unauthenticated registry read must not disclose internal_url."""
    app = create_app()
    original_registry = deps.get_registry_query_service
    original_settings = deps.get_gate_settings
    deps.get_registry_query_service = lambda: FakeRegistryQueryService()
    deps.get_gate_settings = _settings_with_token
    try:
        client = TestClient(app)
        missing = client.get("/v1/registry")
        wrong = client.get("/v1/registry", headers={"X-Admin-Token": "not-the-token"})
    finally:
        deps.get_registry_query_service = original_registry
        deps.get_gate_settings = original_settings

    assert missing.status_code == 401
    assert "internal_url" not in missing.text
    assert "enrich:8000" not in missing.text
    assert wrong.status_code == 401
    assert "internal_url" not in wrong.text


def test_registry_endpoint_returns_registry_snapshot() -> None:
    app = create_app()
    original_registry = deps.get_registry_query_service
    original_settings = deps.get_gate_settings
    deps.get_registry_query_service = lambda: FakeRegistryQueryService()
    deps.get_gate_settings = _settings_with_token
    try:
        client = TestClient(app)
        response = client.get("/v1/registry", headers={"X-Admin-Token": _TOKEN})
    finally:
        deps.get_registry_query_service = original_registry
        deps.get_gate_settings = original_settings

    assert response.status_code == 200
    body = response.json()
    assert "enrich" in body
    assert body["enrich"]["healthy"] is True
