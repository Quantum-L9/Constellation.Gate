from __future__ import annotations

import asyncio
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
from constellation_gate.resilience.deadline import PacketDeadline
from constellation_gate.resilience.idempotency import (
    IdempotencyStore,
    build_idempotency_scope,
    enforce_idempotency,
)
from constellation_gate.resilience.load_shedding import LoadSheddingPolicy
from constellation_gate.resilience.rate_limiter import FixedWindowRateLimiter
from constellation_gate.resilience.replay_guard import ReplayGuard
from constellation_gate.resilience.replay_safety import ReplaySafetyPolicy
from constellation_gate.resilience.retry_policy import RetryPolicy
from constellation_gate.resilience.timeout_policy import TimeoutPolicy

logger = logging.getLogger("constellation_gate.execute")


class ExecuteService:
    """
    Top-level Gate execution coordinator.

    Execution order:
    1. ingress validation
    2. one monotonic packet deadline is created (and never refreshed)
    3. admission control (rate limit, load shedding, backpressure, circuit breaker)
    4. idempotency lookup, namespaced by (tenant, action, key)
    5. replay guard (window-enforcing, bounded)
    6. workflow or dispatch execution under the deadline, replayed ONLY when the
       action is declared replay-safe AND the packet carries a stable key
    7. metrics/logging/tracing
    8. idempotent result caching
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
        self.timeout_policy = TimeoutPolicy()

        # Retry is a mechanism the service may invoke, not a wrapper it applies
        # by default. `replay_safety` decides per packet whether the attempt
        # budget below is usable at all; with the default empty policy every
        # action runs exactly once. Operators opt an action in explicitly.
        self.retry_policy = RetryPolicy()
        self.replay_safety = ReplaySafetyPolicy()

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

            # The one monotonic budget for this operation. Created here, once,
            # immediately after ingress validation; every downstream stage
            # consumes what is left of it and nothing refreshes it.
            deadline = PacketDeadline(self.timeout_policy.resolve(packet))

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

            async def _run() -> TransportPacket:
                if self.workflow_engine.has_workflow(validated_packet.header.action):
                    result = await self.workflow_engine.execute(
                        validated_packet, deadline=deadline
                    )
                else:
                    result = await self.dispatcher.dispatch(validated_packet, deadline=deadline)
                if not isinstance(result, TransportPacket):
                    raise TypeError("execution path must return TransportPacket")
                return result

            # A whole-operation replay needs BOTH an explicit replay-safety
            # contract for the action AND a stable idempotency key. Absent
            # either, attempts == 1: a worker timeout means "no answer", not
            # "no work happened", and re-running blind would duplicate side
            # effects the router cannot see.
            attempts = self.replay_safety.attempts_for(
                packet, max_attempts=self.retry_policy.max_attempts
            )

            try:
                result = await asyncio.wait_for(
                    self.retry_policy.run(_run, max_attempts=attempts, deadline=deadline),
                    # Outer guard only. The authoritative bound is the deadline
                    # itself, which reaches the real worker network timeout.
                    timeout=deadline.remaining_or_raise(),
                )
            except Exception as exc:
                self.circuit_breaker.record_failure()
                self.dead_letter_queue.put(packet=packet, error=exc)
                raise

            self.circuit_breaker.record_success()

            idempotency_scope = build_idempotency_scope(packet)
            if idempotency_scope is not None:
                self.idempotency_store.set(
                    idempotency_scope,
                    result.model_dump_json_dict(),
                )

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

    def _validate(self, body: dict[str, Any]) -> TransportPacket:
        validator = self.ingress_validator
        if not hasattr(validator, "validate"):
            raise TypeError("ingress_validator must expose validate(body) -> TransportPacket")
        packet = validator.validate(body)
        if not isinstance(packet, TransportPacket):
            raise TypeError("ingress_validator returned non-TransportPacket result")
        return packet
