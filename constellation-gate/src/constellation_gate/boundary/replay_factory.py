from __future__ import annotations

from constellation_node_sdk.transport.packet import TransportPacket
from constellation_node_sdk.transport.provenance import RoutingProvenance


class ReplayFactory:
    """
    Derives replay-mode packets for controlled operator or runtime retry paths.

    Replay packets always re-enter Gate and retain lineage continuity while
    setting `header.replay_mode = true`.
    """

    def build(
        self,
        *,
        original: TransportPacket,
        source_node: str,
    ) -> TransportPacket:
        packet = original.derive(
            packet_type=original.header.packet_type,
            action=original.header.action,
            source_node=source_node,
            destination_node="gate",
            reply_to=source_node,
            payload=dict(original.payload),
            timeout_ms=original.header.timeout_ms,
            provenance=RoutingProvenance(
                origin_kind="node" if source_node != "client" else "client",
                requested_action=original.header.action,
                resolved_by_gate=False,
                original_source_node=None if source_node == "client" else source_node,
            ),
        )

        return packet.model_copy(
            update={
                "header": packet.header.model_copy(
                    update={
                        "replay_mode": True,
                        "idempotency_key": original.header.idempotency_key,
                    }
                )
            }
        )
