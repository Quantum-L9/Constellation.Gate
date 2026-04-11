from __future__ import annotations

from fastapi.testclient import TestClient

from constellation_gate.api import dependencies as deps
from constellation_gate.api.main import create_app


class FakeAdminRegistrationService:
    async def register(self, *, request, overwrite: bool, presented_token: str | None):
        del overwrite, presented_token
        return type(
            "Response",
            (),
            {
                "model_dump": lambda self, mode="json": {
                    "registered": [
                        {
                            "node_name": next(iter(request.root.keys())),
                            "healthy": True,
                            "registered": True,
                        }
                    ],
                    "total_nodes": 1,
                }
            },
        )()


def test_admin_register_endpoint_registers_node() -> None:
    app = create_app()
    original = deps.get_admin_registration_service
    deps.get_admin_registration_service = lambda: FakeAdminRegistrationService()
    try:
        client = TestClient(app)
        response = client.post(
            "/v1/admin/register?overwrite=true",
            headers={"X-Admin-Token": "secret"},
            json={
                "enrich": {
                    "internal_url": "http://enrich:8000",
                    "supported_actions": ["enrich"],
                    "priority_class": "P2",
                    "max_concurrent": 50,
                    "health_endpoint": "/v1/health",
                    "timeout_ms": 30000,
                    "metadata": {},
                }
            },
        )
    finally:
        deps.get_admin_registration_service = original

    assert response.status_code == 200
    body = response.json()
    assert body["total_nodes"] == 1
    assert body["registered"][0]["node_name"] == "enrich"
