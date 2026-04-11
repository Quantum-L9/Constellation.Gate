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


def test_registry_endpoint_returns_registry_snapshot() -> None:
    app = create_app()
    original = deps.get_registry_query_service
    deps.get_registry_query_service = lambda: FakeRegistryQueryService()
    try:
        client = TestClient(app)
        response = client.get("/v1/registry")
    finally:
        deps.get_registry_query_service = original

    assert response.status_code == 200
    body = response.json()
    assert "enrich" in body
    assert body["enrich"]["healthy"] is True
