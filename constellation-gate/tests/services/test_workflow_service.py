from __future__ import annotations

import pytest

from constellation_gate.services.workflow_service import WorkflowService
from constellation_node_sdk.transport.packet import TransportPacket, create_transport_packet


class FakeWorkflowEngine:
    def __init__(self, *, has_workflow_result: bool, response: TransportPacket) -> None:
        self._has_workflow_result = has_workflow_result
        self._response = response
        self.calls: list[TransportPacket] = []

    def has_workflow(self, name: str) -> bool:
        return self._has_workflow_result

    async def execute(self, packet: TransportPacket) -> TransportPacket:
        self.calls.append(packet)
        return self._response


@pytest.mark.asyncio
async def test_workflow_service_executes_when_workflow_exists() -> None:
    packet = create_transport_packet(
        action="full_pipeline",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )
    response = packet.derive(
        packet_type="response",
        source_node="gate",
        destination_node="client",
        reply_to="gate",
        payload={"status": "completed", "score": 99},
    )
    engine = FakeWorkflowEngine(has_workflow_result=True, response=response)
    service = WorkflowService(engine)

    result = await service.maybe_execute(packet)

    assert result.payload["score"] == 99
    assert len(engine.calls) == 1
    assert service.has_workflow("full_pipeline") is True


@pytest.mark.asyncio
async def test_workflow_service_returns_original_packet_when_no_workflow_exists() -> None:
    packet = create_transport_packet(
        action="score",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )
    engine = FakeWorkflowEngine(has_workflow_result=False, response=packet)
    service = WorkflowService(engine)

    result = await service.maybe_execute(packet)

    assert result.header.packet_id == packet.header.packet_id
    assert len(engine.calls) == 0
    assert service.has_workflow("score") is False
