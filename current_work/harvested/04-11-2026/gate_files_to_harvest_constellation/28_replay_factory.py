from __future__ import annotations

from constellation_node_sdk.transport.packet import TransportPacket


class ReplayFactory:
    """
    Derives replay-mode packets for controlled operator or runtime retry paths.
    """

    def build(
        self,
        *,
        original: TransportPacket,
        source_node: str,
    ) -> TransportPacket:
        return original.derive(
            packet_type=original.header.packet_type,
            action=original.header.action,
            source_node=source_node,
            destination_node="gate",
            reply_to=source_node,
            payload=dict(original.payload),
            timeout_ms=original.header.timeout_ms,
        ).model_copy(
            update={
                "header": original.derive(
                    packet_type=original.header.packet_type,
                    action=original.header.action,
                    source_node=source_node,
                    destination_node="gate",
                    reply_to=source_node,
                    payload=dict(original.payload),
                    timeout_ms=original.header.timeout_ms,
                ).header.model_copy(update={"replay_mode": True})
            }
        )
