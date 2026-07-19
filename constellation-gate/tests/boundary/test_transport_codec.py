from __future__ import annotations

from constellation_node_sdk.transport.packet import TransportPacket, create_transport_packet

from constellation_gate.boundary.transport_codec import decode_request_body, encode_response_body


def test_decode_request_body_round_trips_canonical_transport_packet() -> None:
    packet = create_transport_packet(
        action="enrich",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )

    decoded = decode_request_body(packet.model_dump_json_dict())

    assert isinstance(decoded, TransportPacket)
    assert decoded.header.packet_id == packet.header.packet_id
    assert decoded.security.transport_hash == packet.security.transport_hash


def test_encode_response_body_returns_json_safe_dict() -> None:
    packet = create_transport_packet(
        action="enrich",
        payload={"status": "completed"},
        tenant="tenant-a",
        destination_node="client",
        source_node="gate",
        reply_to="gate",
    )

    body = encode_response_body(packet)

    assert isinstance(body, dict)
    assert body["header"]["action"] == "enrich"
    assert body["payload"]["status"] == "completed"
