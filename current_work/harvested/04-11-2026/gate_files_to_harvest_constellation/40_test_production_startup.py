from __future__ import annotations

from fastapi.testclient import TestClient

from constellation_gate.api.main import create_app


def test_app_lifespan_starts_runtime_and_health_surface() -> None:
    app = create_app()

    with TestClient(app) as client:
        runtime = client.app.state.runtime
        assert runtime.http_client_manager is not None
        assert runtime.http_client_manager.started is True

        response = client.get("/v1/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] in {"healthy", "degraded"}
