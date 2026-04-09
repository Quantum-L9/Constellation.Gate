from __future__ import annotations

import pytest

from constellation_gate.services.execute_service import ExecuteService
from constellation_node_sdk.transport.packet import TransportPacket, create_transport_packet


class StaticValidator:
    def __init__(self, packet: TransportPacket) -> None:
        self.packet = packet

    def validate(self, _body: dict) -> TransportPacket:
        return self.packet


class AlwaysFailDispatcher:
    async def dispatch(self, _packet: TransportPacket) -> TransportPacket:
        raise RuntimeError("dispatch failed")


class NoWorkflow:
    def has_workflow(self, _action: str) -> bool:
        return False


@pytest.mark.asyncio
async def test_execute_service_captures_terminal_failure_in_dead_letter_queue() -> None:
    packet = create_transport_packet(
        action="score",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )

    service = ExecuteService(
        local_node="gate",
        ingress_validator=StaticValidator(packet),
        dispatcher=AlwaysFailDispatcher(),
        workflow_engine=NoWorkflow(),
        registry=None,
    )
    service.retry_policy.max_attempts = 1

    with pytest.raises(RuntimeError, match="dispatch failed"):
        await service.execute({})

    assert service.dead_letter_queue.size() == 1
    entry = service.dead_letter_queue.latest()
    assert entry is not None
    assert entry.packet_id == str(packet.header.packet_id)
    assert entry.action == "score"
    assert entry.error_type == "RuntimeError"
    assert entry.error_message == "dispatch failed"
    assert entry.packet["header"]["action"] == "score"
