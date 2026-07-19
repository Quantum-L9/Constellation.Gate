from __future__ import annotations

from constellation_node_sdk.transport.packet import TransportPacket

from constellation_gate.orchestration.workflow_engine import WorkflowEngine


class WorkflowService:
    """
    Thin service wrapper around the Gate workflow engine.
    """

    def __init__(self, engine: WorkflowEngine) -> None:
        self._engine = engine

    def has_workflow(self, action: str) -> bool:
        return self._engine.has_workflow(action)

    async def maybe_execute(self, packet: TransportPacket) -> TransportPacket:
        if self._engine.has_workflow(packet.header.action):
            return await self._engine.execute(packet)
        return packet
