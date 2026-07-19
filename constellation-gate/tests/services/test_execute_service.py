from __future__ import annotations

import pytest
from constellation_node_sdk.transport.packet import TransportPacket, create_transport_packet

from constellation_gate.services.execute_service import ExecuteService


class FakeIngressValidator:
    def __init__(self, packet: TransportPacket) -> None:
        self._packet = packet

    def validate(self, body: dict) -> TransportPacket:
        assert body == self._packet.model_dump_json_dict()
        return self._packet


class FakeDispatcher:
    def __init__(self, response_packet: TransportPacket) -> None:
        self.response_packet = response_packet
        self.calls: list[TransportPacket] = []

    async def dispatch(self, packet: TransportPacket) -> TransportPacket:
        self.calls.append(packet)
        return self.response_packet


class FakeWorkflowEngine:
    def __init__(self, *, has_workflow: bool, response_packet: TransportPacket) -> None:
        self._has_workflow = has_workflow
        self._response_packet = response_packet
        self.calls: list[TransportPacket] = []

    def has_workflow(self, name: str) -> bool:
        return self._has_workflow

    async def execute(self, packet: TransportPacket) -> TransportPacket:
        self.calls.append(packet)
        return self._response_packet


class FakeRegistry:
    pass


@pytest.mark.asyncio
async def test_execute_service_dispatches_atomic_request_when_no_workflow() -> None:
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
        payload={"status": "completed", "score": 90},
    )

    dispatcher = FakeDispatcher(response_packet=response_packet)
    workflow_engine = FakeWorkflowEngine(has_workflow=False, response_packet=response_packet)
    service = ExecuteService(
        local_node="gate",
        ingress_validator=FakeIngressValidator(request_packet),
        dispatcher=dispatcher,
        workflow_engine=workflow_engine,
        registry=FakeRegistry(),
    )

    result = await service.execute(request_packet.model_dump_json_dict())

    assert result.payload["score"] == 90
    assert len(dispatcher.calls) == 1
    assert len(workflow_engine.calls) == 0


@pytest.mark.asyncio
async def test_execute_service_uses_workflow_engine_for_composite_action() -> None:
    request_packet = create_transport_packet(
        action="full_pipeline",
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
        payload={"status": "completed", "score": 93},
    )

    dispatcher = FakeDispatcher(response_packet=response_packet)
    workflow_engine = FakeWorkflowEngine(has_workflow=True, response_packet=response_packet)
    service = ExecuteService(
        local_node="gate",
        ingress_validator=FakeIngressValidator(request_packet),
        dispatcher=dispatcher,
        workflow_engine=workflow_engine,
        registry=FakeRegistry(),
    )

    result = await service.execute(request_packet.model_dump_json_dict())

    assert result.payload["score"] == 93
    assert len(dispatcher.calls) == 0
    assert len(workflow_engine.calls) == 1
