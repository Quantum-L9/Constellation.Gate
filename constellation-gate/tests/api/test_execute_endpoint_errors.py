from __future__ import annotations

from fastapi.testclient import TestClient

from constellation_gate.api import dependencies as deps
from constellation_gate.api.main import create_app


class FailingExecuteService:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    async def execute(self, body: dict):
        del body
        raise self.exc


def test_execute_endpoint_maps_timeout_to_504() -> None:
    app = create_app()
    original = deps.get_execute_service
    deps.get_execute_service = lambda: FailingExecuteService(TimeoutError("too slow"))
    try:
        client = TestClient(app)
        response = client.post("/v1/execute", json={})
    finally:
        deps.get_execute_service = original

    assert response.status_code == 504
    body = response.json()
    assert body["detail"]["code"] == "execution_timeout"


def test_execute_endpoint_maps_value_error_to_400() -> None:
    app = create_app()
    original = deps.get_execute_service
    deps.get_execute_service = lambda: FailingExecuteService(ValueError("bad body"))
    try:
        client = TestClient(app)
        response = client.post("/v1/execute", json={})
    finally:
        deps.get_execute_service = original

    assert response.status_code == 400
    body = response.json()
    assert body["detail"]["code"] == "invalid_request"
    assert body["detail"]["message"] == "bad body"
