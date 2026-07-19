from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

REGISTRY = CollectorRegistry(auto_describe=True)

REQUESTS_TOTAL = Counter(
    "constellation_gate_requests_total",
    "Total Gate execute requests",
    ["action", "status"],
    registry=REGISTRY,
)

DISPATCHES_TOTAL = Counter(
    "constellation_gate_dispatches_total",
    "Total Gate worker dispatches",
    ["action", "target_node", "status"],
    registry=REGISTRY,
)

IN_FLIGHT = Gauge(
    "constellation_gate_in_flight_requests",
    "Current in-flight execute requests",
    registry=REGISTRY,
)

EXECUTION_LATENCY_SECONDS = Histogram(
    "constellation_gate_execution_latency_seconds",
    "End-to-end Gate execution latency in seconds",
    ["action"],
    registry=REGISTRY,
)


def record_request(*, action: str, status: str) -> None:
    REQUESTS_TOTAL.labels(action=action.strip().lower(), status=status.strip().lower()).inc()


def record_dispatch(*, action: str, target_node: str, status: str) -> None:
    DISPATCHES_TOTAL.labels(
        action=action.strip().lower(),
        target_node=target_node.strip().lower(),
        status=status.strip().lower(),
    ).inc()


def observe_execution_latency(*, action: str, seconds: float) -> None:
    EXECUTION_LATENCY_SECONDS.labels(action=action.strip().lower()).observe(seconds)


def increment_in_flight() -> None:
    IN_FLIGHT.inc()


def decrement_in_flight() -> None:
    IN_FLIGHT.dec()
