from __future__ import annotations

from constellation_node_sdk.transport.packet import TransportPacket
from constellation_node_sdk.transport.provenance import RoutingProvenance


class DelegationFactory:
    """
    Creates node-origin Gate reentry packets for orchestrated follow-up work.

    This is the legal pattern for:
    node -> gate -> worker

    It does not create peer-targeted packets.
    """

    def build(
        self,
        *,
        parent: TransportPacket,
        local_node: str,
        action: str,
        payload: dict,
        idempotency_key: str | None = None,
        timeout_ms: int | None = None,
    ) -> TransportPacket:
        return parent.derive(
            action=action,
            source_node=local_node,
            destination_node="gate",
            reply_to=local_node,
            payload=payload,
            idempotency_key=idempotency_key,
            timeout_ms=parent.header.timeout_ms if timeout_ms is None else timeout_ms,
            provenance=RoutingProvenance(
                origin_kind="node",
                requested_action=action,
                resolved_by_gate=False,
                original_source_node=local_node,
            ),
        )
