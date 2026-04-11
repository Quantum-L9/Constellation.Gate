from __future__ import annotations

from constellation_node_sdk.transport.packet import TransportPacket


class FailureFactory:
    """
    Builds sanitized failure packets from an originating request packet.
    """

    def build(
        self,
        *,
        request_packet: TransportPacket,
        source_node: str,
        error: Exception,
        code: str = "execution_failed",
    ) -> TransportPacket:
        return request_packet.derive(
            packet_type="failure",
            source_node=source_node,
            destination_node=request_packet.address.reply_to,
            reply_to=source_node,
            payload={
                "status": "failed",
                "code": code,
                "error_type": error.__class__.__name__,
                "message": str(error),
            },
        )
