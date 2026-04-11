from __future__ import annotations

from typing import Any

from constellation_node_sdk.transport.packet import TransportPacket


def decode_request_body(body: dict[str, Any]) -> TransportPacket:
    """
    Decode a canonical request body into a TransportPacket.

    Gate accepts canonical TransportPacket JSON only.
    """
    if not isinstance(body, dict):
        raise ValueError("request body must be a JSON object")
    return TransportPacket.model_validate(body)


def encode_response_body(packet: TransportPacket) -> dict[str, Any]:
    """
    Encode a canonical TransportPacket for HTTP JSON response.
    """
    return packet.model_dump_json_dict()
