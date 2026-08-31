from __future__ import annotations

from typing import Any

import httpx
from constellation_node_sdk.transport.hop_trace import make_dispatch_hop, make_ingress_hop
from constellation_node_sdk.transport.packet import TransportPacket
from constellation_node_sdk.transport.provenance import RoutingProvenance

from constellation_gate.boundary.routing_policy import validate_gate_dispatch_policy
from constellation_gate.resilience.deadline import Deadline
from constellation_gate.routing.node_registry import NodeRegistry
from constellation_gate.routing.resolver import RouteResolver
from constellation_gate.runtime.node_limits import PerNodeLimiterManager


class Dispatcher:
    """
    Gate-owned internal dispatcher.

    Only Gate may derive direct worker-targeted dispatch packets.
    """

    def __init__(
        self,
        *,
        local_node: str,
        registry: NodeRegistry,
        client: httpx.AsyncClient | None = None,
        node_limits: PerNodeLimiterManager | None = None,
    ) -> None:
        self._local_node = local_node.strip().lower()
        self._registry = registry
        self._resolver = RouteResolver(registry, local_node=self._local_node)
        self._client = client
        self._node_limits = node_limits

    async def dispatch(
        self,
        packet: TransportPacket,
        *,
        deadline: Deadline | None = None,
    ) -> TransportPacket:
        target = self._resolver.resolve(packet)

        ingress_observed = packet.with_hop(
            make_ingress_hop(
                packet=packet,
                node=self._local_node,
                action=packet.header.action,
                status="validated",
            )
        )

        dispatch_base = ingress_observed.derive(
            packet_type=ingress_observed.header.packet_type,
            action=ingress_observed.header.action,
            source_node=self._local_node,
            destination_node=target.node_name,
            reply_to=self._local_node,
            payload=dict(ingress_observed.payload),
            provenance=RoutingProvenance(
                origin_kind="gate",
                requested_action=ingress_observed.header.action,
                resolved_by_gate=True,
                # Canonical worker ingress requires route_kind. The SDK's
                # validate_execute_ingress_packet() accepts only
                # "external_ingress" on /v1/execute, so a Gate-authored dispatch
                # that omits it is rejected by every SDK-based worker.
                route_kind="external_ingress",
                original_source_node=ingress_observed.address.source_node,
            ),
        )

        # The dispatch hop must be keyed to the freshly derived packet's id;
        # deriving mints a new packet_id, so build the hop from dispatch_base
        # (not the pre-derive packet) or with_hop() will reject the mismatch.
        # derive() also resets hop_trace: hops are per-packet observational
        # state bound to one packet_id, while lineage carries the ancestry.
        dispatch_packet = dispatch_base.with_hop(
            make_dispatch_hop(
                packet=dispatch_base,
                node=self._local_node,
                action=dispatch_base.header.action,
                target_node=target.node_name,
                status="delegated",
            )
        )

        validate_gate_dispatch_policy(dispatch_packet, local_node=self._local_node)

        # Acquire the per-node concurrency permit (the authoritative admission
        # gate) before touching the registry's active counter, and only release
        # what this call actually acquired so a rejected dispatch cannot free an
        # in-flight peer's slot.
        acquired_limit = False
        incremented = False
        try:
            if self._node_limits is not None:
                self._node_limits.ensure_node_limit(target.node_name, target.max_concurrent)
                await self._node_limits.acquire(target.node_name)
                acquired_limit = True

            self._registry.increment_active(target.node_name)
            incremented = True

            try:
                response = await self._post_dispatch_packet(
                    url=f"{target.internal_url}/v1/execute",
                    timeout_seconds=self._attempt_timeout_seconds(
                        node_timeout_ms=target.timeout_ms,
                        deadline=deadline,
                    ),
                    packet=dispatch_packet,
                )
            except httpx.TransportError as exc:
                self._registry.mark_unhealthy(target.node_name)
                raise RuntimeError(f"dispatch transport error to {target.node_name!r}") from exc
            return TransportPacket.model_validate(response)
        finally:
            if incremented:
                self._registry.decrement_active(target.node_name)
            if acquired_limit and self._node_limits is not None:
                self._node_limits.release(target.node_name)

    @staticmethod
    def _attempt_timeout_seconds(
        *,
        node_timeout_ms: int,
        deadline: Deadline | None,
    ) -> float:
        """Budget for one worker attempt (ADR-GATE-008).

        A downstream attempt never gets a fresh full timeout. It receives
        ``min(remaining packet budget, node-configured cap)``; with no deadline
        supplied the node cap stands alone.
        """
        node_cap_seconds = node_timeout_ms / 1000
        if deadline is None:
            return node_cap_seconds

        deadline.raise_if_expired(stage="worker dispatch")
        return deadline.bounded_by(node_cap_seconds)

    async def _post_dispatch_packet(
        self,
        *,
        url: str,
        timeout_seconds: float,
        packet: TransportPacket,
    ) -> dict[str, Any]:
        if self._client is not None:
            response = await self._client.post(
                url,
                json=packet.model_dump_json_dict(),
                headers={"Content-Type": "application/json"},
                timeout=timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("dispatch response body must be a JSON object")
            return body

        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(
                url,
                json=packet.model_dump_json_dict(),
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("dispatch response body must be a JSON object")
            return body
