from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Callable
from typing import Any

from constellation_node_sdk.transport.packet import TransportPacket

from constellation_gate.observability.logging import log_packet_event
from constellation_gate.observability.metrics import (
    decrement_in_flight,
    increment_in_flight,
    observe_execution_latency,
    record_dispatch,
    record_request,
)
from constellation_gate.observability.tracing import packet_trace
from constellation_gate.resilience.backpressure import BackpressurePolicy
from constellation_gate.resilience.circuit_breaker import CircuitBreaker
from constellation_gate.resilience.dead_letter_queue import DeadLetterQueue
from constellation_gate.resilience.deadline import Deadline, deadline_for_packet
from constellation_gate.resilience.idempotency import IdempotencyStore, enforce_idempotency
from constellation_gate.resilience.load_shedding import LoadSheddingPolicy
from constellation_gate.resilience.rate_limiter import FixedWindowRateLimiter
from constellation_gate.resilience.replay_guard import ReplayGuard
from constellation_gate.resilience.replay_safety import REPLAY_SAFE_MAX_ATTEMPTS, max_attempts_for
from constellation_gate.resilience.retry_policy import RetryPolicy
from constellation_gate.resilience.timeout_policy import TimeoutPolicy

logger = logging.getLogger("constellation_gate.execute")


def _accepts_deadline(func: Any) -> bool:
    """True when ``func`` exposes a ``deadline`` keyword parameter."""
    try:
        params = inspect.signature(func).parameters
    except (TypeError, ValueError):  # builtins / C callables
        return False
    deadline_param = params.get("deadline")
    if deadline_param is not None:
        return True
    return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


def _is_terminal_success(result: TransportPacket) -> bool:
    """True when ``result`` is a successful answer worth caching under its key.

    Reads transport-level signals only: the packet type the SDK runtime emits
    for a handler exception (``failure``) and the status the runtime records on
    the response hop. Domain payloads stay opaque (ADR-GATE-003).
    """
    if result.header.packet_type == "failure":
        return False
    for hop in reversed(result.hop_trace):
        if hop.direction == "response":
            return hop.status != "failed"
    return True


class ExecuteService:
    """
    Top-level Gate execution coordinator.

    Execution order:
    1. ingress validation
    2. admission control (rate limit, load shedding, backpressure, circuit breaker)
    3. idempotency lookup, namespaced by (tenant, action, key)
    4. replay guard
    5. one monotonic packet deadline derived from the packet budget
    6. workflow or dispatch execution, bounded by that deadline, with a
       per-action attempt budget that defaults to a single attempt
    7. metrics/logging/tracing
    8. idempotent result caching under the namespaced key
    9. dead-letter capture on terminal execution failure
    """

    def __init__(
        self,
        *,
        local_node: str,
        ingress_validator: Any,
        dispatcher: Any,
        workflow_engine: Any,
        registry: Any,
    ) -> None:
        self.local_node = local_node.strip().lower()
        self.ingress_validator = ingress_validator
        self.dispatcher = dispatcher
        self.workflow_engine = workflow_engine
        self.registry = registry

        self.idempotency_store = IdempotencyStore()
        self.replay_guard = ReplayGuard()
        # ``retry_policy`` is a TEMPLATE, not the effective policy. It supplies
        # delay/backoff/retryable-exception shape, and its ``max_attempts`` acts
        # as an operator CEILING that can only narrow the attempt budget. The
        # effective budget per packet is resolved by the replay-safety registry
        # (ADR-GATE-007), which the ceiling can never widen.
        self.retry_policy = RetryPolicy(max_attempts=REPLAY_SAFE_MAX_ATTEMPTS)
        self.timeout_policy = TimeoutPolicy()

        # Admission-control primitives default to effectively-unlimited so the
        # standard execution path is unchanged until an operator (or test) tunes
        # them. Each guard fails closed with an explicit typed exception.
        self.rate_limiter = FixedWindowRateLimiter(max_requests=1_000_000, window_seconds=1.0)
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=1_000_000, recovery_timeout_seconds=30.0
        )
        self.load_shedding = LoadSheddingPolicy(max_in_flight=1_000_000)
        self.backpressure = BackpressurePolicy(max_queue_depth=1_000_000)
        self.dead_letter_queue = DeadLetterQueue()

        self.queue_depth_provider: Callable[[], int] = lambda: 0
        self._in_flight_requests = 0

    async def execute(self, body: dict[str, Any]) -> TransportPacket:
        start = time.perf_counter()
        packet: TransportPacket | None = None
        action_for_metrics = "unknown"
        in_flight_incremented = False

        try:
            packet = self._validate(body)
            action_for_metrics = packet.header.action

            log_packet_event(
                logger,
                event="gate.ingress",
                packet=packet,
                trace=packet_trace(packet),
            )

            self.rate_limiter.allow(key=packet.address.source_node)
            self.load_shedding.enforce(in_flight=self._in_flight_requests)
            self.backpressure.enforce(queue_depth=self.queue_depth_provider())
            self.circuit_breaker.before_call()

            increment_in_flight()
            self._in_flight_requests += 1
            in_flight_incremented = True

            cached = enforce_idempotency(packet, self.idempotency_store)
            if cached is not None:
                cached_packet = TransportPacket.model_validate(cached)
                record_request(action=packet.header.action, status="cached")
                observe_execution_latency(
                    action=packet.header.action,
                    seconds=time.perf_counter() - start,
                )
                log_packet_event(
                    logger,
                    event="gate.cached",
                    packet=cached_packet,
                    trace=packet_trace(cached_packet),
                )
                return cached_packet

            self.replay_guard.check_and_record(str(packet.header.packet_id))

            validated_packet = packet

            # ADR-GATE-008: one monotonic deadline governs routing, retry sleeps,
            # worker transport, and response validation for this packet.
            timeout_seconds = self.timeout_policy.resolve(packet)
            deadline = deadline_for_packet(
                packet,
                default_timeout_ms=self.timeout_policy.default_timeout_ms,
            )

            async def _run() -> TransportPacket:
                if self.workflow_engine.has_workflow(validated_packet.header.action):
                    result = await self._run_workflow(validated_packet, deadline)
                else:
                    result = await self._run_dispatch(validated_packet, deadline)
                if not isinstance(result, TransportPacket):
                    raise TypeError("execution path must return TransportPacket")
                return result

            # ADR-GATE-007: the attempt budget is resolved per packet. Absent an
            # explicit replay-safe contract AND a stable idempotency identity,
            # a side-effect-capable operation is attempted exactly once.
            retry_policy = self._retry_policy_for(packet)

            try:
                result = await asyncio.wait_for(
                    retry_policy.run(_run, deadline=deadline),
                    timeout=timeout_seconds,
                )
            except Exception as exc:
                self.circuit_breaker.record_failure()
                self.dead_letter_queue.put(packet=packet, error=exc)
                raise

            self.circuit_breaker.record_success()

            # ADR-GATE-009: cache under (tenant, action, key), never the raw key.
            # Only a terminal SUCCESS answer is cached. A worker `failure` packet,
            # or a response whose own response hop reports `failed`, is a
            # transport-level failure of THIS attempt; caching it would answer
            # every later retry of the same logical operation with the stale
            # failure and defeat the retry the idempotency key exists to make
            # safe (seam audit 2026-09-02, SEAM-013).
            if _is_terminal_success(result):
                self.idempotency_store.set_for_packet(packet, result.model_dump_json_dict())

            record_request(action=packet.header.action, status="completed")
            if (
                result.address.source_node == self.local_node
                and result.address.destination_node != self.local_node
            ):
                record_dispatch(
                    action=packet.header.action,
                    target_node=result.address.destination_node,
                    status="delegated",
                )

            elapsed = time.perf_counter() - start
            observe_execution_latency(action=packet.header.action, seconds=elapsed)

            log_packet_event(
                logger,
                event="gate.completed",
                packet=result,
                trace=packet_trace(result),
                duration_ms=int(elapsed * 1000),
            )
            return result

        except Exception as exc:
            record_request(action=action_for_metrics, status="failed")
            if packet is not None:
                log_packet_event(
                    logger,
                    event="gate.failure",
                    packet=packet,
                    error_type=exc.__class__.__name__,
                    error_message=str(exc),
                )
            logger.exception("gate.failure", exc_info=exc)
            raise
        finally:
            if in_flight_incremented:
                self._in_flight_requests -= 1
                decrement_in_flight()

    def _retry_policy_for(self, packet: TransportPacket) -> RetryPolicy:
        """Resolve the effective whole-operation attempt budget for one packet.

        The replay-safety registry is authoritative; the configured template
        acts only as a ceiling. An action with no explicit replay-safe contract
        -- ``converge`` among them -- is attempted exactly once, whatever the
        template says.
        """
        template = self.retry_policy
        resolved = max_attempts_for(
            action=packet.header.action,
            has_idempotency_key=bool(packet.header.idempotency_key),
        )
        effective = min(resolved, template.max_attempts)

        if effective == template.max_attempts:
            return template

        return RetryPolicy(
            max_attempts=effective,
            delay_seconds=template.delay_seconds,
            backoff_multiplier=template.backoff_multiplier,
            retryable_exceptions=template.retryable_exceptions,
        )

    async def _run_dispatch(
        self,
        packet: TransportPacket,
        deadline: Deadline,
    ) -> TransportPacket:
        result = await self._call_with_optional_deadline(self.dispatcher.dispatch, packet, deadline)
        return self._as_transport_packet(result, source="dispatcher")

    async def _run_workflow(
        self,
        packet: TransportPacket,
        deadline: Deadline,
    ) -> TransportPacket:
        result = await self._call_with_optional_deadline(
            self.workflow_engine.execute, packet, deadline
        )
        return self._as_transport_packet(result, source="workflow engine")

    @staticmethod
    def _as_transport_packet(result: Any, *, source: str) -> TransportPacket:
        """Narrow an injected collaborator's result to the canonical type.

        Collaborators are duck-typed, so this is the boundary where a non-packet
        return is caught -- named, rather than surfacing later as an attribute
        error somewhere in the response path.
        """
        if not isinstance(result, TransportPacket):
            raise TypeError(f"{source} must return TransportPacket, got {type(result).__name__}")
        return result

    @staticmethod
    async def _call_with_optional_deadline(
        func: Any,
        packet: TransportPacket,
        deadline: Deadline,
    ) -> Any:
        """Pass the shared deadline to collaborators that accept one.

        Collaborators are injected, so some (notably test doubles and older
        engines) expose ``(packet)`` only. Probing the signature keeps those
        working without letting the deadline silently vanish for the real
        dispatcher, whose behaviour is asserted directly in the routing tests.
        """
        if _accepts_deadline(func):
            return await func(packet, deadline=deadline)
        return await func(packet)

    def _validate(self, body: dict[str, Any]) -> TransportPacket:
        validator = self.ingress_validator
        if not hasattr(validator, "validate"):
            raise TypeError("ingress_validator must expose validate(body) -> TransportPacket")
        packet = validator.validate(body)
        if not isinstance(packet, TransportPacket):
            raise TypeError("ingress_validator returned non-TransportPacket result")
        return packet
