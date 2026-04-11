from __future__ import annotations

from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry
from constellation_node_sdk.transport.packet import TransportPacket


class RouteResolver:
    """
    Resolve a canonical TransportPacket to a single target node registration.

    Resolution rules:
    - client-origin and node-origin packets targeting Gate are resolved by action
    - Gate-authored dispatch packets targeting a worker are resolved by explicit destination
    - any other destination shape is rejected
    """

    def __init__(self, registry: NodeRegistry, *, local_node: str = "gate") -> None:
        self._registry = registry
        self._local_node = local_node.strip().lower()

    def resolve(self, packet: TransportPacket) -> NodeRegistration:
        destination = packet.address.destination_node.strip().lower()
        origin_kind = packet.provenance.origin_kind

        if destination == self._local_node:
            return self._resolve_gate_bound(packet)

        if origin_kind == "gate":
            return self._resolve_gate_dispatch(packet)

        raise LookupError(
            f"packet destination {destination!r} is not routable for origin_kind={origin_kind!r}"
        )

    def _resolve_gate_bound(self, packet: TransportPacket) -> NodeRegistration:
        action = packet.header.action.strip().lower()
        if not action:
            raise LookupError("packet action must not be empty for Gate-bound resolution")
        return self._registry.resolve_action(action)

    def _resolve_gate_dispatch(self, packet: TransportPacket) -> NodeRegistration:
        destination = packet.address.destination_node.strip().lower()

        if destination == self._local_node:
            raise LookupError("Gate-authored dispatch packets must not target Gate itself")

        if packet.provenance.resolved_by_gate is not True:
            raise LookupError("Gate-authored dispatch packets must set resolved_by_gate=true")

        if packet.address.source_node.strip().lower() != self._local_node:
            raise LookupError("Gate-authored dispatch packet source_node must equal local Gate node")

        return self._registry.resolve_destination(destination)
