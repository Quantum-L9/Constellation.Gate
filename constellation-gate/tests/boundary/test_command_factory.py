from __future__ import annotations

from constellation_node_sdk.transport.packet import create_transport_packet

from constellation_gate.boundary.command_factory import CommandFactory, ExecutionContext


def test_command_factory_builds_execute_command() -> None:
    packet = create_transport_packet(
        action="score",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )
    context = ExecutionContext(local_node="gate", request_id="req-1")

    command = CommandFactory().build(packet=packet, context=context)

    assert command.packet.header.action == "score"
    assert command.context.local_node == "gate"
    assert command.context.request_id == "req-1"
