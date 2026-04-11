from __future__ import annotations

from constellation_gate.boundary.failure_factory import FailureFactory
from constellation_node_sdk.transport.packet import create_transport_packet


def test_failure_factory_builds_failure_packet() -> None:
    request_packet = create_transport_packet(
        action="score",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )

    packet = FailureFactory().build(
        request_packet=request_packet,
        source_node="gate",
        error=RuntimeError("boom"),
    )

    assert packet.header.packet_type == "failure"
    assert packet.address.source_node == "gate"
    assert packet.address.destination_node == "client"
    assert packet.payload["status"] == "failed"
    assert packet.payload["error_type"] == "RuntimeError"
