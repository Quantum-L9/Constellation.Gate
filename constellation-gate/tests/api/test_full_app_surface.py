from __future__ import annotations

from fastapi.testclient import TestClient

from constellation_gate.api import dependencies as deps
from constellation_gate.api.main import create_app
from constellation_gate.config.settings import GateSettings

_TOKEN = "surface-admin-token"


def test_full_app_surface_exposes_expected_routes() -> None:
    app = create_app()
    original_settings = deps.get_gate_settings
    deps.get_gate_settings = lambda: GateSettings(
        environment="local", local_node="gate", admin_token=_TOKEN
    )
    client = TestClient(app)

    try:
        routes = {
            "/v1/health": client.get("/v1/health"),
            "/metrics": client.get("/metrics"),
            "/v1/registry": client.get("/v1/registry", headers={"X-Admin-Token": _TOKEN}),
        }
    finally:
        deps.get_gate_settings = original_settings

    assert routes["/v1/health"].status_code == 200
    assert routes["/metrics"].status_code == 200
    assert routes["/v1/registry"].status_code == 200

    health = routes["/v1/health"].json()
    assert health["status"] == "healthy"
    assert health["service_name"] == "constellation-gate"

    assert "text/plain" in routes["/metrics"].headers["content-type"]

    registry = routes["/v1/registry"].json()
    assert isinstance(registry, dict)
