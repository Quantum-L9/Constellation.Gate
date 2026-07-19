from __future__ import annotations

import pytest
from constellation_node_sdk.transport.packet import create_transport_packet

from constellation_gate.services.execute_service import ExecuteService


class DummyValidator:
    def validate(self, body):
        from constellation_node_sdk.transport.packet import TransportPacket

        return TransportPacket.model_validate(body)


class DummyDispatcher:
    async def dispatch(self, packet):
        return packet


class DummyWorkflow:
    def has_workflow(self, action):
        return False


@pytest.mark.asyncio
async def test_idempotency_returns_cached() -> None:
    service = ExecuteService(
        local_node="gate",
        ingress_validator=DummyValidator(),
        dispatcher=DummyDispatcher(),
        workflow_engine=DummyWorkflow(),
        registry=None,
    )

    packet = create_transport_packet(
        action="score",
        payload={"x": 1},
        tenant="t",
        destination_node="gate",
        source_node="client",
        reply_to="client",
        idempotency_key="abc",
    )

    first = await service.execute(packet.model_dump_json_dict())
    second = await service.execute(packet.model_dump_json_dict())

    assert first.header.packet_id == second.header.packet_id
