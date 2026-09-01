from __future__ import annotations

from collections.abc import Callable

import httpx
from constellation_node_sdk.gate_authority import (
    GateDispatchTransport,
    GateDispatchTransportConfig,
    WorkerConnectionError,
)
from constellation_node_sdk.transport.hop_trace import make_dispatch_hop, make_ingress_hop
from constellation_node_sdk.transport.packet import TransportPacket
from constellation_node_sdk.transport.provenance import RoutingProvenance

from constellation_gate.boundary.routing_policy import validate_gate_dispatch_policy
from constellation_gate.resilience.deadline import Deadline, DeadlineExceeded
from constellation_gate.routing.node_registry import NodeRegistry
from constellation_gate.routing.resolver import RouteResolver
from constellation_gate.runtime.node_limits import PerNodeLimiterManager


class Dispatcher:
    """
    Gate-owned internal dispatcher.

    Only Gate may derive direct worker-targeted dispatch packets.

    DIVISION OF AUTHORITY -- read before adding an HTTP call here.

    Gate decides *where*: which worker answers this action, whether that node is
    eligible, how much of the one packet budget the attempt may spend, and what
    a failure means for that node's health. Gate_SDK decides *how*: validation,
    signing, serialization, the single network attempt, the deadline actually
    applied, response decoding, and canonical response validation.

    This module therefore holds no HTTP. Every canonical Gate->worker hop leaves
    through ``GateDispatchTransport.send_gate_authored_packet``, which accepts
    only a packet carrying Gate's own routing authority. There is no Gate-local
    worker transport any more, and
    ``tests/architecture/test_architecture_drift_guards.py`` fails the build if
    one reappears.
    """

    def __init__(
        self,
        *,
        local_node: str,
        registry: NodeRegistry,
        dispatch_config: GateDispatchTransportConfig | None = None,
        transport: GateDispatchTransport | None = None,
        client: httpx.AsyncClient | None = None,
        client_provider: Callable[[], httpx.AsyncClient | None] | None = None,
        node_limits: PerNodeLimiterManager | None = None,
    ) -> None:
        self._local_node = local_node.strip().lower()
        self._registry = registry
        self._resolver = RouteResolver(registry, local_node=self._local_node)
        self._dispatch_config = dispatch_config or GateDispatchTransportConfig(
            local_gate_node=self._local_node
        )
        # An explicitly supplied transport wins (wiring and tests). Otherwise one
        # is built per dispatch around the resolved pooled client: the transport
        # object is a thin holder, while the connection pool -- the thing that is
        # expensive to recreate -- lives in the client and is reused.
        self._transport = transport
        self._client = client
        # The pooled client only exists after ASGI startup, while the dispatcher
        # is built during wiring. A provider defers resolution to dispatch time
        # so the shared connection pool is actually used, instead of every
        # dispatch opening and discarding a client of its own.
        self._client_provider = client_provider
        self._node_limits = node_limits

    async def dispatch(
        self,
        packet: TransportPacket,
        *,
        deadline: Deadline | None = None,
    ) -> TransportPacket:
        target = self._resolver.resolve(packet)

        # Budget first, before any packet is minted: an already-expired deadline
        # should fail as a deadline, not as a malformed dispatch downstream.
        worker_budget_ms = self._worker_budget_ms(
            node_timeout_ms=target.timeout_ms,
            deadline=deadline,
        )

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
            # INV-GATE-DOWNSTREAM-DEADLINE-IDENTITY. The child advertises the
            # bounded remaining budget, not the root packet's original timeout.
            # The SDK derives the socket deadline from this same field and the
            # worker's runtime bounds its handler with it, so Gate's wait, the
            # network deadline, and the worker's own budget are one number.
            # Inheriting the root value here would tell a worker it had 30s
            # while Gate waited 2s -- the exact drift this closure removes.
            timeout_ms=worker_budget_ms,
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
                return await self._resolve_transport().send_gate_authored_packet(
                    packet=dispatch_packet,
                    target_node=target.node_name,
                    worker_base_url=target.internal_url,
                )
            except WorkerConnectionError as exc:
                # Only an unreachable node is evidence the node is down. A
                # timeout or an unusable response is not, and marking those
                # unhealthy would eject a slow-but-working worker from routing.
                self._registry.mark_unhealthy(target.node_name)
                self._attribute(exc, target.node_name)
                raise
            except Exception as exc:
                # A bare re-raise, never ``raise exc from ...``: the SDK already
                # chained the underlying httpx failure as ``__cause__``, and
                # re-raising with an explicit cause would overwrite or suppress
                # it. Gate adds attribution, not a new link in the chain.
                self._attribute(exc, target.node_name)
                raise
        finally:
            if incremented:
                self._registry.decrement_active(target.node_name)
            if acquired_limit and self._node_limits is not None:
                self._node_limits.release(target.node_name)

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------

    def _resolve_transport(self) -> GateDispatchTransport:
        if self._transport is not None:
            return self._transport
        # Never used as an async context manager, so it creates no client and
        # closes none: the pooled client's lifecycle stays with Gate's runtime.
        return GateDispatchTransport(self._dispatch_config, client=self._resolve_client())

    def _resolve_client(self) -> httpx.AsyncClient | None:
        if self._client is not None:
            return self._client
        if self._client_provider is None:
            return None
        return self._client_provider()

    @staticmethod
    def _attribute(exc: BaseException, node_name: str) -> None:
        """Attach the resolved node to an SDK dispatch failure.

        Attribution only -- the SDK's exception type still classifies the
        failure, and Gate adds nothing to that judgement. The node name is
        knowledge Gate has and the SDK deliberately does not (it is told a
        target, it never resolves one), so recording it here is what lets an
        operator attribute a 502 without re-parsing a message.
        """
        if getattr(exc, "node_name", None) is None:
            exc.node_name = node_name  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Deadline
    # ------------------------------------------------------------------

    @staticmethod
    def _worker_budget_ms(
        *,
        node_timeout_ms: int,
        deadline: Deadline | None,
    ) -> int:
        """Budget for one worker attempt, in milliseconds (ADR-GATE-008).

        A downstream attempt never gets a fresh full timeout. It receives
        ``min(remaining packet budget, node-configured cap)``; with no deadline
        supplied the node cap stands alone.

        Milliseconds because this number is written into the dispatch packet's
        ``header.timeout_ms``, from which both the SDK's socket deadline and the
        worker's handler budget are derived. Returning seconds for the socket
        while the header carried something else is precisely the split this
        replaces.
        """
        node_cap_seconds = node_timeout_ms / 1000
        if deadline is None:
            budget_seconds = node_cap_seconds
        else:
            deadline.raise_if_expired(stage="worker dispatch")
            budget_seconds = deadline.bounded_by(node_cap_seconds)

        budget_ms = int(budget_seconds * 1000)
        if budget_ms <= 0:
            # Sub-millisecond remainder. Reported as the deadline failure it is,
            # rather than handed to the SDK to reject as a malformed budget.
            raise DeadlineExceeded(f"remaining budget for worker dispatch rounds to {budget_ms}ms")
        return budget_ms
