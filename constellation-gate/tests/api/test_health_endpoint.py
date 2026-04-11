from __future__ import annotations

from fastapi.testclient import TestClient

from constellation_gate.api.main import create_app


def test_health_endpoint_returns_healthy_status() -> None:
    app = create_app()
    client = TestClient(app)

    response = client.get("/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["service_name"] == "constellation-gate"
    assert body["node_name"] == "gate"
    assert "environment" in body
