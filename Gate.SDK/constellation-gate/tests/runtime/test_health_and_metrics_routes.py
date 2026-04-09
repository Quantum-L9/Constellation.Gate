from __future__ import annotations

from fastapi.testclient import TestClient

from constellation_gate.api.main import create_app


def test_health_and_metrics_routes_exist_and_are_operational() -> None:
    app = create_app()
    client = TestClient(app)

    health = client.get("/v1/health")
    metrics = client.get("/metrics")

    assert health.status_code == 200
    assert metrics.status_code == 200

    health_body = health.json()
    assert health_body["status"] == "healthy"
    assert health_body["service_name"] == "constellation-gate"

    assert "text/plain" in metrics.headers["content-type"]
