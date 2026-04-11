from __future__ import annotations

import pytest

from constellation_gate.orchestration.workflow_engine import WorkflowEngine
from constellation_gate.orchestration.workflow_models import WorkflowDefinition, WorkflowStep
from constellation_gate.services.execute_service import ExecuteService
from constellation_node_sdk.transport.packet import TransportPacket, create_transport_packet


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
        raise AssertionError("workflow path should use workflow engine-owned dispatcher calls only")


class WorkflowDispatcher:
    def __init__(self) -> None:
        self.calls: list[TransportPacket] = []

    async def dispatch(self, packet: TransportPacket) -> TransportPacket:
        self.calls.append(packet)
        if packet.header.action == "enrich":
            return packet.derive(
                packet_type="response",
                source_node="gate",
                destination_node="gate",
                reply_to="gate",
                payload={"status": "completed", "data": {"industry": "fintech"}},
            )
        if packet.header.action == "score":
            return packet.derive(
                packet_type="response",
                source_node="gate",
                destination_node="gate",
                reply_to="gate",
                payload={"status": "completed", "score": 91},
            )
        raise AssertionError(f"unexpected action: {packet.header.action}")


@pytest.mark.asyncio
async def test_workflow_execute_path_runs_end_to_end() -> None:
    request_packet = create_transport_packet(
        action="full_pipeline",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )

    workflow_dispatcher = WorkflowDispatcher()
    workflow_engine = WorkflowEngine(
        definitions={
            "full_pipeline": WorkflowDefinition(
                name="full_pipeline",
                steps=(
                    WorkflowStep(name="enrich", action="enrich", merge_strategy="merge_results"),
                    WorkflowStep(name="score", action="score", merge_strategy="merge_payload"),
                ),
            )
        },
        dispatcher=workflow_dispatcher,
        local_node="gate",
    )

    service = ExecuteService(
        local_node="gate",
        ingress_validator=StaticValidator(request_packet),
        dispatcher=NeverDispatch(),
        workflow_engine=workflow_engine,
        registry=None,
    )
    service.retry_policy.max_attempts = 1

    result = await service.execute({})

    assert result.header.packet_type == "response"
    assert result.address.source_node == "gate"
    assert result.address.destination_node == "client"
    assert result.payload["entity_id"] == "42"
    assert result.payload["industry"] == "fintech"
    assert result.payload["score"] == 91
    assert len(workflow_dispatcher.calls) == 2
    assert all(call.address.destination_node == "gate" for call in workflow_dispatcher.calls)
