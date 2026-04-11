from __future__ import annotations

from fastapi.testclient import TestClient

from constellation_gate.api import dependencies as deps
from constellation_gate.api.main import create_app


class FailingExecuteService:
    async def execute(self, body: dict):
        del body
        raise ValueError("request body must be a JSON object")


def test_execute_endpoint_rejects_invalid_request_shape() -> None:
    app = create_app()
    original = deps.get_execute_service
    deps.get_execute_service = lambda: FailingExecuteService()
    try:
        client = TestClient(app)
        response = client.post("/v1/execute", json={})
    finally:
        deps.get_execute_service = original

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_request"
