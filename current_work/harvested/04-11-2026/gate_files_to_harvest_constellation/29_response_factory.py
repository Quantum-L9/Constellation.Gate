from __future__ import annotations

from constellation_node_sdk.transport.packet import TransportPacket


class ResponseFactory:
    """
    Builds canonical response packets from a request packet and payload result.
    """

    def build(
        self,
        *,
        request_packet: TransportPacket,
        source_node: str,
        payload: dict,
    ) -> TransportPacket:
        return request_packet.derive(
            packet_type="response",
            source_node=source_node,
            destination_node=request_packet.address.reply_to,
            reply_to=source_node,
            payload=payload,
        )
