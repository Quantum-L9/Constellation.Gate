from __future__ import annotations

from fastapi.testclient import TestClient

from constellation_gate.api import dependencies as deps
from constellation_gate.api.main import create_app
from constellation_node_sdk.transport.packet import create_transport_packet


class FakeExecuteService:
    def __init__(self, response_packet) -> None:
        self.response_packet = response_packet
        self.calls: list[dict] = []

    async def execute(self, body: dict):
        self.calls.append(body)
        return self.response_packet


def test_execute_endpoint_returns_canonical_packet_response() -> None:
    app = create_app()

    request_packet = create_transport_packet(
        action="score",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )
    response_packet = request_packet.derive(
        packet_type="response",
        source_node="gate",
        destination_node="client",
        reply_to="gate",
        payload={"status": "completed", "score": 88},
    )

    fake_service = FakeExecuteService(response_packet)
    original = deps.get_execute_service
    deps.get_execute_service = lambda: fake_service
    try:
        client = TestClient(app)
        response = client.post("/v1/execute", json=request_packet.model_dump_json_dict())
    finally:
        deps.get_execute_service = original

    assert response.status_code == 200
    body = response.json()
    assert body["header"]["packet_type"] == "response"
    assert body["payload"]["score"] == 88
    assert len(fake_service.calls) == 1
