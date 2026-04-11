from __future__ import annotations

from fastapi.testclient import TestClient
from fastapi import FastAPI

from constellation_gate.runtime.metrics_endpoint import router


def test_metrics_endpoint_exposes_prometheus_format() -> None:
    app = FastAPI()
    app.include_router(router)

    client = TestClient(app)
    response = client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
