from __future__ import annotations

from fastapi import HTTPException

from constellation_gate.boundary.ingress_validator import IngressValidationError
from constellation_gate.boundary.routing_policy import RoutingPolicyError
from constellation_gate.resilience.backpressure import BackpressureExceededError
from constellation_gate.resilience.circuit_breaker import CircuitBreakerOpenError
from constellation_gate.resilience.load_shedding import LoadShedError
from constellation_gate.resilience.rate_limiter import RateLimitExceededError
from constellation_gate.routing.worker_transport import (
    WorkerTransportError,
)

_ADMISSION_ERRORS = (
    RateLimitExceededError,
    LoadShedError,
    BackpressureExceededError,
    CircuitBreakerOpenError,
)


def to_http_exception(exc: Exception) -> HTTPException:
    """
    Map Gate-layer exceptions to safe HTTP responses.
    """
    if isinstance(exc, IngressValidationError):
        return HTTPException(
            status_code=400,
            detail={
                "code": "invalid_transport_packet",
                "message": str(exc),
            },
        )

    if isinstance(exc, _ADMISSION_ERRORS):
        return HTTPException(
            status_code=429,
            detail={
                "code": "admission_rejected",
                "message": str(exc),
            },
        )

    if isinstance(exc, RoutingPolicyError):
        return HTTPException(
            status_code=403,
            detail={
                "code": "routing_policy_violation",
                "message": str(exc),
            },
        )

    if isinstance(exc, PermissionError):
        return HTTPException(
            status_code=401,
            detail={
                "code": "admin_auth_failed",
                "message": str(exc),
            },
        )

    if isinstance(exc, LookupError):
        return HTTPException(
            status_code=404,
            detail={
                "code": "not_found",
                "message": str(exc),
            },
        )

    # A worker timeout is a gateway timeout, and it must be checked before the
    # generic WorkerTransportError branch (WorkerTimeoutError is both).
    if isinstance(exc, TimeoutError):
        return HTTPException(
            status_code=504,
            detail={
                "code": "execution_timeout",
                "message": str(exc),
            },
        )

    # An upstream worker failing is not a Gate bug. Reporting it as 500 hides an
    # upstream dependency failure behind Gate's own error surface and sends an
    # operator to the wrong service.
    if isinstance(exc, WorkerTransportError):
        return HTTPException(
            status_code=502,
            detail={
                "code": "worker_transport_failed",
                "message": str(exc),
                "node": exc.node_name,
            },
        )

    if isinstance(exc, ValueError):
        return HTTPException(
            status_code=400,
            detail={
                "code": "invalid_request",
                "message": str(exc),
            },
        )

    return HTTPException(
        status_code=500,
        detail={
            "code": "internal_error",
            "message": "internal server error",
        },
    )
