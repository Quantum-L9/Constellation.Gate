from __future__ import annotations

import pytest

from constellation_gate.services.execute_service import ExecuteService
from constellation_node_sdk.transport.packet import create_transport_packet


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
async def test_replay_guard_blocks_duplicate_packet() -> None:
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
    )

    await service.execute(packet.model_dump_json_dict())

    with pytest.raises(ValueError):
        await service.execute(packet.model_dump_json_dict())
