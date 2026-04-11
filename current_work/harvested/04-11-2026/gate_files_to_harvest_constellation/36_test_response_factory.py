from __future__ import annotations

from constellation_gate.boundary.response_factory import ResponseFactory
from constellation_node_sdk.transport.packet import create_transport_packet


def test_response_factory_builds_response_packet() -> None:
    request_packet = create_transport_packet(
        action="score",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="score",
        source_node="gate",
        reply_to="gate",
    )

    packet = ResponseFactory().build(
        request_packet=request_packet,
        source_node="score",
        payload={"status": "completed", "score": 91},
    )

    assert packet.header.packet_type == "response"
    assert packet.address.source_node == "score"
    assert packet.address.destination_node == "gate"
    assert packet.payload["score"] == 91
