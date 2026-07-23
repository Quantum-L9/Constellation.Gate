from __future__ import annotations

import pytest
from constellation_node_sdk.transport.packet import TransportPacket, create_transport_packet

from constellation_gate.services.execute_service import ExecuteService


class StaticValidator:
    def __init__(self, packet: TransportPacket) -> None:
        self.packet = packet

    def validate(self, _body: dict) -> TransportPacket:
        return self.packet


class NeverDispatch:
    def __init__(self) -> None:
        self.calls = 0

    async def dispatch(self, _packet: TransportPacket) -> TransportPacket:
        self.calls += 1
        raise AssertionError("dispatcher should not be called for workflow action")


class WorkflowEngineStub:
    def __init__(self) -> None:
        self.calls = 0

    def has_workflow(self, action: str) -> bool:
        return action == "full_pipeline"

    async def execute(self, packet: TransportPacket) -> TransportPacket:
        self.calls += 1
        return packet.derive(
            packet_type="response",
            source_node="gate",
            destination_node=packet.address.reply_to,
            reply_to="gate",
            payload={"status": "completed", "workflow": "full_pipeline"},
        )


@pytest.mark.asyncio
async def test_execute_service_uses_workflow_engine_path() -> None:
    packet = create_transport_packet(
        action="full_pipeline",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )

    workflow_engine = WorkflowEngineStub()
    dispatcher = NeverDispatch()

    service = ExecuteService(
        local_node="gate",
        ingress_validator=StaticValidator(packet),
        dispatcher=dispatcher,
        workflow_engine=workflow_engine,
        registry=None,
    )
    service.retry_policy.max_attempts = 1

    result = await service.execute({})

    assert result.header.packet_type == "response"
    assert result.address.source_node == "gate"
    assert result.address.destination_node == "client"
    assert result.payload["workflow"] == "full_pipeline"
    assert workflow_engine.calls == 1
    assert dispatcher.calls == 0
