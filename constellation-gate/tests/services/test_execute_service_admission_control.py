from __future__ import annotations

import pytest

from constellation_gate.resilience.backpressure import BackpressureExceededError
from constellation_gate.resilience.circuit_breaker import CircuitBreakerOpenError
from constellation_gate.resilience.load_shedding import LoadShedError
from constellation_gate.resilience.rate_limiter import RateLimitExceededError
from constellation_gate.services.execute_service import ExecuteService
from constellation_node_sdk.transport.packet import TransportPacket, create_transport_packet


class SequenceValidator:
    def __init__(self, packets: list[TransportPacket]) -> None:
        self._packets = list(packets)

    def validate(self, _body: dict) -> TransportPacket:
        return self._packets.pop(0)


class EchoDispatcher:
    async def dispatch(self, packet: TransportPacket) -> TransportPacket:
        return packet.derive(
            packet_type="response",
            source_node="gate",
            destination_node="worker-a",
            reply_to="gate",
            payload={"status": "completed"},
        )


class FailingDispatcher:
    async def dispatch(self, _packet: TransportPacket) -> TransportPacket:
        raise RuntimeError("worker failure")


class NoWorkflow:
    def has_workflow(self, _action: str) -> bool:
        return False


@pytest.mark.asyncio
async def test_execute_service_rate_limits_by_source_node() -> None:
    packet_a = create_transport_packet(
        action="score",
        payload={"x": 1},
        tenant="t",
        destination_node="gate",
        source_node="client-a",
        reply_to="client-a",
    )
    packet_b = create_transport_packet(
        action="score",
        payload={"x": 2},
        tenant="t",
        destination_node="gate",
        source_node="client-a",
        reply_to="client-a",
    )

    service = ExecuteService(
        local_node="gate",
        ingress_validator=SequenceValidator([packet_a, packet_b]),
        dispatcher=EchoDispatcher(),
        workflow_engine=NoWorkflow(),
        registry=None,
    )
    service.rate_limiter = service.rate_limiter.__class__(max_requests=1, window_seconds=60.0)

    first = await service.execute({})
    assert first.payload["status"] == "completed"

    with pytest.raises(RateLimitExceededError):
        await service.execute({})


@pytest.mark.asyncio
async def test_execute_service_rejects_on_load_shedding_and_backpressure() -> None:
    packet_load = create_transport_packet(
        action="score",
        payload={"x": 1},
        tenant="t",
        destination_node="gate",
        source_node="client-load",
        reply_to="client-load",
    )
    packet_queue = create_transport_packet(
        action="score",
        payload={"x": 2},
        tenant="t",
        destination_node="gate",
        source_node="client-queue",
        reply_to="client-queue",
    )

    service = ExecuteService(
        local_node="gate",
        ingress_validator=SequenceValidator([packet_load, packet_queue]),
        dispatcher=EchoDispatcher(),
        workflow_engine=NoWorkflow(),
        registry=None,
    )

    service.load_shedding = service.load_shedding.__class__(max_in_flight=1)
    service._in_flight_requests = 1
    with pytest.raises(LoadShedError):
        await service.execute({})

    service._in_flight_requests = 0
    service.backpressure = service.backpressure.__class__(max_queue_depth=1)
    service.queue_depth_provider = lambda: 1
    with pytest.raises(BackpressureExceededError):
        await service.execute({})


@pytest.mark.asyncio
async def test_execute_service_respects_open_circuit_breaker() -> None:
    packet_a = create_transport_packet(
        action="score",
        payload={"x": 1},
        tenant="t",
        destination_node="gate",
        source_node="client-a",
        reply_to="client-a",
    )
    packet_b = create_transport_packet(
        action="score",
        payload={"x": 2},
        tenant="t",
        destination_node="gate",
        source_node="client-b",
        reply_to="client-b",
    )

    service = ExecuteService(
        local_node="gate",
        ingress_validator=SequenceValidator([packet_a, packet_b]),
        dispatcher=FailingDispatcher(),
        workflow_engine=NoWorkflow(),
        registry=None,
    )
    service.retry_policy.max_attempts = 1
    service.circuit_breaker = service.circuit_breaker.__class__(
        failure_threshold=1,
        recovery_timeout_seconds=60.0,
    )

    with pytest.raises(RuntimeError, match="worker failure"):
        await service.execute({})

    with pytest.raises(CircuitBreakerOpenError):
        await service.execute({})
