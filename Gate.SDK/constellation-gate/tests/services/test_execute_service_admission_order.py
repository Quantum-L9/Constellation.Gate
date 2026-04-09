from __future__ import annotations

import pytest

from constellation_gate.services.execute_service import ExecuteService
from constellation_node_sdk.transport.packet import TransportPacket, create_transport_packet


class StaticValidator:
    def __init__(self, packet: TransportPacket) -> None:
        self.packet = packet

    def validate(self, _body: dict) -> TransportPacket:
        return self.packet


class EchoDispatcher:
    async def dispatch(self, packet: TransportPacket) -> TransportPacket:
        return packet.derive(
            packet_type="response",
            source_node="gate",
            destination_node="worker-a",
            reply_to="gate",
            payload={"status": "completed"},
        )


class NoWorkflow:
    def has_workflow(self, _action: str) -> bool:
        return False


@pytest.mark.asyncio
async def test_execute_service_checks_admission_before_dispatch() -> None:
    packet = create_transport_packet(
        action="score",
        payload={"x": 1},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client-a",
        reply_to="client-a",
    )

    service = ExecuteService(
        local_node="gate",
        ingress_validator=StaticValidator(packet),
        dispatcher=EchoDispatcher(),
        workflow_engine=NoWorkflow(),
        registry=None,
    )
    service.rate_limiter = service.rate_limiter.__class__(max_requests=1, window_seconds=60.0)

    first = await service.execute({})
    assert first.payload["status"] == "completed"

    with pytest.raises(Exception):
        await service.execute({})
