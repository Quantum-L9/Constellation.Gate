from __future__ import annotations

from fastapi.testclient import TestClient

from constellation_gate.api import dependencies as deps
from constellation_gate.api.main import create_app
from constellation_gate.resilience.rate_limiter import RateLimitExceededError


class FailingExecuteService:
    async def execute(self, body: dict):
        del body
        raise RateLimitExceededError("rate limit exceeded for key='client'")


def test_execute_endpoint_maps_policy_runtime_failures() -> None:
    app = create_app()
    original = deps.get_execute_service
    deps.get_execute_service = lambda: FailingExecuteService()
    try:
        client = TestClient(app)
        response = client.post("/v1/execute", json={})
    finally:
        deps.get_execute_service = original

    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "admission_rejected"
