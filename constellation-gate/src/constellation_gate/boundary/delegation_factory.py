from __future__ import annotations

from typing import Any

from constellation_node_sdk.transport.hashing import compute_transport_hash
from constellation_node_sdk.transport.packet import TransportPacket
from constellation_node_sdk.transport.provenance import RoutingProvenance


def _apply_idempotency_key(packet: TransportPacket, idempotency_key: str) -> TransportPacket:
    """
    Return a copy of ``packet`` carrying ``idempotency_key`` on its header.

    ``TransportPacket.derive`` inherits the parent's idempotency key and does not
    accept an override, so a delegated packet that needs its own key must be
    re-finalized. We recompute only the transport hash (which covers the header)
    using the SDK's canonical hashing helper; payload and payload_hash are
    unchanged, so integrity validation on construction succeeds.
    """
    new_header = packet.header.model_copy(update={"idempotency_key": idempotency_key})
    zeroed_security = packet.security.model_copy(
        update={
            "transport_hash": "0" * 64,
            "signature": None,
            "signature_algorithm": None,
            "signing_key_id": None,
        }
    )
    provisional = packet.model_copy(update={"header": new_header, "security": zeroed_security})
    transport_hash = compute_transport_hash(provisional)
    final_security = zeroed_security.model_copy(update={"transport_hash": transport_hash})
    return TransportPacket(
        header=new_header,
        address=packet.address,
        tenant=packet.tenant,
        payload=packet.payload,
        security=final_security,
        governance=packet.governance,
        provenance=packet.provenance,
        delegation_chain=packet.delegation_chain,
        hop_trace=packet.hop_trace,
        lineage=packet.lineage,
        attachments=packet.attachments,
    )


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
        payload: dict[str, Any],
        idempotency_key: str | None = None,
        timeout_ms: int | None = None,
    ) -> TransportPacket:
        child = parent.derive(
            action=action,
            source_node=local_node,
            destination_node="gate",
            reply_to=local_node,
            payload=payload,
            timeout_ms=parent.header.timeout_ms if timeout_ms is None else timeout_ms,
            provenance=RoutingProvenance(
                origin_kind="node",
                requested_action=action,
                resolved_by_gate=False,
                original_source_node=local_node,
            ),
        )
        if idempotency_key is not None and child.header.idempotency_key != idempotency_key:
            child = _apply_idempotency_key(child, idempotency_key)
        return child
