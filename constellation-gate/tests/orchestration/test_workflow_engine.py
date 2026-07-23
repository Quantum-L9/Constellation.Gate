from __future__ import annotations

import pytest
from constellation_node_sdk.transport.packet import TransportPacket, create_transport_packet

from constellation_gate.orchestration.workflow_engine import WorkflowEngine
from constellation_gate.orchestration.workflow_models import WorkflowDefinition, WorkflowStep


class FakeDispatcher:
    def __init__(self) -> None:
        self.calls: list[TransportPacket] = []

    async def dispatch(self, packet: TransportPacket) -> TransportPacket:
        self.calls.append(packet)
        if packet.header.action == "enrich":
            return packet.derive(
                packet_type="response",
                source_node="enrich",
                destination_node="gate",
                reply_to="enrich",
                payload={"status": "completed", "data": {"industry": "fintech"}},
            )
        if packet.header.action == "score":
            return packet.derive(
                packet_type="response",
                source_node="score",
                destination_node="gate",
                reply_to="score",
                payload={"status": "completed", "score": 91},
            )
        raise AssertionError(f"unexpected action: {packet.header.action}")


@pytest.mark.asyncio
async def test_workflow_engine_executes_steps_sequentially_and_merges_payload() -> None:
    dispatcher = FakeDispatcher()
    engine = WorkflowEngine(
        definitions={
            "full_pipeline": WorkflowDefinition(
                name="full_pipeline",
                steps=(
                    WorkflowStep(name="enrich", action="enrich", merge_strategy="merge_results"),
                    WorkflowStep(name="score", action="score", merge_strategy="merge_payload"),
                ),
            )
        },
        dispatcher=dispatcher,
        local_node="gate",
    )

    request = create_transport_packet(
        action="full_pipeline",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )

    response = await engine.execute(request)

    assert response.header.packet_type == "response"
    assert response.address.source_node == "gate"
    assert response.address.destination_node == "client"
    assert response.payload["entity_id"] == "42"
    assert response.payload["industry"] == "fintech"
    assert response.payload["score"] == 91
    assert len(dispatcher.calls) == 2
    assert dispatcher.calls[0].address.destination_node == "gate"
    assert dispatcher.calls[1].address.destination_node == "gate"


@pytest.mark.asyncio
async def test_workflow_engine_skips_conditional_step_when_false() -> None:
    dispatcher = FakeDispatcher()
    engine = WorkflowEngine(
        definitions={
            "conditional_pipeline": WorkflowDefinition(
                name="conditional_pipeline",
                steps=(
                    WorkflowStep(name="enrich", action="enrich", merge_strategy="merge_results"),
                    WorkflowStep(
                        name="score",
                        action="score",
                        merge_strategy="merge_payload",
                        condition="payload['run_score'] == True",
                    ),
                ),
            )
        },
        dispatcher=dispatcher,
        local_node="gate",
    )

    request = create_transport_packet(
        action="conditional_pipeline",
        payload={"entity_id": "42", "run_score": False},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )

    response = await engine.execute(request)

    assert response.payload["industry"] == "fintech"
    assert "score" not in response.payload
    assert len(dispatcher.calls) == 1
