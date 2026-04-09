from __future__ import annotations

from fastapi.testclient import TestClient

from constellation_gate.api.main import create_app


def test_full_app_surface_exposes_expected_routes() -> None:
    app = create_app()
    client = TestClient(app)

    routes = {
        "/v1/health": client.get("/v1/health"),
        "/metrics": client.get("/metrics"),
        "/v1/registry": client.get("/v1/registry"),
    }

    assert routes["/v1/health"].status_code == 200
    assert routes["/metrics"].status_code == 200
    assert routes["/v1/registry"].status_code == 200

    health = routes["/v1/health"].json()
    assert health["status"] == "healthy"
    assert health["service_name"] == "constellation-gate"

    assert "text/plain" in routes["/metrics"].headers["content-type"]

    registry = routes["/v1/registry"].json()
    assert isinstance(registry, dict)
