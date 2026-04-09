from __future__ import annotations

from fastapi.testclient import TestClient

from constellation_gate.api.main import create_app


def test_metrics_endpoint_is_exposed_in_main_app() -> None:
    app = create_app()
    client = TestClient(app)

    response = client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "constellation_gate_requests_total" in response.text
