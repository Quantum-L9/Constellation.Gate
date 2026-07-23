from __future__ import annotations

from constellation_node_sdk.transport.packet import TransportPacket


class RoutingPolicyError(Exception):
    """Raised when a packet violates Gate routing policy."""


def validate_node_origin_policy(
    packet: TransportPacket,
    *,
    local_node: str,
    known_nodes: set[str],
) -> None:
    """
    Enforce that node-originated packets re-enter Gate instead of targeting peers directly.

    The core invariant is re-entry: a node-originated packet must target the
    local Gate, never a peer node directly, and its declared original source must
    be self-consistent. Membership in ``known_nodes`` is intentionally not
    required here -- upstream orchestrators that are not registered worker nodes
    must still be able to route follow-up work back through Gate (the canonical
    node -> Gate -> worker pattern). ``known_nodes`` is retained for callers that
    want to layer their own allow-listing on top.
    """
    del known_nodes  # accepted for interface stability; not used for enforcement

    normalized_local = local_node.strip().lower()
    source = packet.address.source_node
    destination = packet.address.destination_node
    origin_kind = packet.provenance.origin_kind

    if origin_kind == "node":
        if destination != normalized_local:
            raise RoutingPolicyError(
                f"node-originated packets must target {normalized_local!r}, got {destination!r}"
            )
        if packet.provenance.original_source_node not in {None, source}:
            raise RoutingPolicyError(
                "node-originated packet original_source_node must match source_node"
            )


def validate_gate_dispatch_policy(packet: TransportPacket, *, local_node: str) -> None:
    """
    Enforce that only Gate may emit direct worker-targeted dispatch packets.
    """
    normalized_local = local_node.strip().lower()

    if packet.provenance.origin_kind != "gate":
        raise RoutingPolicyError(
            "direct worker-targeted dispatch packets must have origin_kind='gate'"
        )

    if packet.address.source_node != normalized_local:
        raise RoutingPolicyError("Gate dispatch packet source_node must equal local Gate node")

    if packet.address.destination_node == normalized_local:
        raise RoutingPolicyError(
            "Gate dispatch packet destination_node must not point back to Gate"
        )

    if packet.provenance.resolved_by_gate is not True:
        raise RoutingPolicyError("Gate dispatch packet must set resolved_by_gate=true")
