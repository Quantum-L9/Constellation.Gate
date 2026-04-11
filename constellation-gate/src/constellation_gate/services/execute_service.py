from __future__ import annotations

import logging
import time
from typing import Any

from constellation_gate.observability.logging import log_packet_event
from constellation_gate.observability.metrics import (
    decrement_in_flight,
    increment_in_flight,
    record_dispatch,
    record_request,
)
from constellation_gate.observability.tracing import packet_trace
from constellation_gate.resilience.idempotency import IdempotencyStore, enforce_idempotency
from constellation_gate.resilience.replay_guard import ReplayGuard
from constellation_gate.resilience.retry_policy import RetryPolicy
from constellation_gate.resilience.timeout_policy import TimeoutPolicy
from constellation_node_sdk.transport.packet import TransportPacket

logger = logging.getLogger("constellation_gate.execute")


class ExecuteService:
    def __init__(
        self,
        *,
        local_node: str,
        ingress_validator,
        dispatcher,
        workflow_engine,
        registry,
    ) -> None:
        self.local_node = local_node
        self.ingress_validator = ingress_validator
        self.dispatcher = dispatcher
        self.workflow_engine = workflow_engine
        self.registry = registry

        self.idempotency_store = IdempotencyStore()
        self.replay_guard = ReplayGuard()
        self.retry_policy = RetryPolicy()
        self.timeout_policy = TimeoutPolicy()

    async def execute(self, body: dict[str, Any]) -> TransportPacket:
        increment_in_flight()
        start = time.time()

        try:
            packet = self.ingress_validator.validate(body)

            log_packet_event(logger, event="gate.ingress", packet=packet)

            cached = enforce_idempotency(packet, self.idempotency_store)
            if cached:
                record_request(action=packet.header.action, status="cached")
                return TransportPacket.model_validate(cached)

            self.replay_guard.check_and_record(str(packet.header.packet_id))

            timeout = self.timeout_policy.resolve(packet)

            async def _run():
                if self.workflow_engine.has_workflow(packet.header.action):
                    return await self.workflow_engine.execute(packet)
                return await self.dispatcher.dispatch(packet)

            result = await self.retry_policy.run(_run)

            self.idempotency_store.set(
                packet.header.idempotency_key or str(packet.header.packet_id),
                result.model_dump_json_dict(),
            )

            record_request(action=packet.header.action, status="completed")
            record_dispatch(
                action=packet.header.action,
                target_node=result.address.destination_node,
                status="delegated",
            )

            log_packet_event(
                logger,
                event="gate.completed",
                packet=result,
                trace=packet_trace(result),
                duration_ms=int((time.time() - start) * 1000),
            )

            return result

        except Exception as exc:
            record_request(action="unknown", status="failed")
            logger.exception("gate.failure", exc_info=exc)
            raise
        finally:
            decrement_in_flight()
