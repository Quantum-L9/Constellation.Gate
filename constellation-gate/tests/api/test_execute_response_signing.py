"""Gate re-signs the response it returns under its own key.

Before this, /v1/execute relayed the worker's packet verbatim, worker
signature included. The SDK verifies every signature it is handed, so a
caller in a signed topology needed every worker's verifying key -- exactly the
peer-key awareness Gate-only routing forbids (ADR-002).
"""

from __future__ import annotations

import pytest
from constellation_node_sdk import sign_transport_packet, verify_transport_packet_signature
from constellation_node_sdk.transport.packet import TransportPacket, create_transport_packet
from fastapi.testclient import TestClient

from constellation_gate.api import dependencies as deps
from constellation_gate.api.main import create_app
from constellation_gate.config.settings import GateSettings

GATE_KEY = "gate-shared-secret"
WORKER_KEY = "worker-shared-secret"


class _FakeExecuteService:
    def __init__(self, response_packet) -> None:
        self.response_packet = response_packet

    async def execute(self, body: dict):
        return self.response_packet


def _worker_signed_response() -> tuple[TransportPacket, TransportPacket]:
    request = create_transport_packet(
        action="converge",
        payload={"entity": {"id": "res.partner:55"}},
        tenant="plasticos",
        destination_node="gate",
        source_node="odoo",
        reply_to="odoo",
    )
    response = request.derive(
        packet_type="response",
        source_node="enrichment-engine",
        destination_node="odoo",
        reply_to="enrichment-engine",
        payload={"state": "completed", "fields": {"city": "Charlotte"}},
    )
    signed_by_worker = sign_transport_packet(
        response, key=WORKER_KEY, key_id="eie-k1", algorithm="hmac-sha256"
    )
    return request, signed_by_worker


@pytest.fixture
def signed_gate(monkeypatch: pytest.MonkeyPatch):
    settings = GateSettings(
        environment="local", local_node="gate", signing_key=GATE_KEY, signing_key_id="gate-k1"
    )
    monkeypatch.setattr(deps, "get_gate_settings", lambda: settings)
    return settings


def test_response_is_re_signed_under_gate_identity(signed_gate, monkeypatch) -> None:
    request, worker_signed = _worker_signed_response()
    monkeypatch.setattr(deps, "get_execute_service", lambda: _FakeExecuteService(worker_signed))

    with TestClient(create_app()) as client:
        response = client.post("/v1/execute", json=request.model_dump_json_dict())

    assert response.status_code == 200
    packet = TransportPacket.model_validate(response.json())
    assert packet.security.signing_key_id == "gate-k1"
    assert packet.security.signature_algorithm == "hmac-sha256"
    assert verify_transport_packet_signature(packet, key_resolver={"gate-k1": GATE_KEY}) is True
    # The worker's key is no longer needed -- or accepted -- by the caller.
    with pytest.raises(Exception, match="no verifying key"):
        verify_transport_packet_signature(packet, key_resolver={"eie-k1": WORKER_KEY})
    # Business content is untouched.
    assert packet.payload == worker_signed.payload
    assert packet.address.source_node == "enrichment-engine"
    assert packet.header.packet_id == worker_signed.header.packet_id


def test_unsigned_gate_returns_the_packet_unchanged(monkeypatch) -> None:
    settings = GateSettings(environment="local", local_node="gate")
    monkeypatch.setattr(deps, "get_gate_settings", lambda: settings)
    request, worker_signed = _worker_signed_response()
    monkeypatch.setattr(deps, "get_execute_service", lambda: _FakeExecuteService(worker_signed))

    with TestClient(create_app()) as client:
        response = client.post("/v1/execute", json=request.model_dump_json_dict())

    packet = TransportPacket.model_validate(response.json())
    assert packet.security.signing_key_id == "eie-k1"
    assert packet.security.signature == worker_signed.security.signature
