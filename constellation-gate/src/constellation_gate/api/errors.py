from __future__ import annotations

from constellation_node_sdk.gate_authority import (
    GateDispatchAuthorityError,
    GateDispatchConfigurationError,
    GateDispatchError,
    GateDispatchSecurityError,
)
from fastapi import HTTPException

from constellation_gate.boundary.ingress_validator import IngressValidationError
from constellation_gate.boundary.routing_policy import RoutingPolicyError
from constellation_gate.resilience.backpressure import BackpressureExceededError
from constellation_gate.resilience.circuit_breaker import CircuitBreakerOpenError
from constellation_gate.resilience.load_shedding import LoadShedError
from constellation_gate.resilience.rate_limiter import RateLimitExceededError

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

    # Checked before the dispatch branches below: the SDK's WorkerTimeoutError is
    # both, and a timeout is a gateway timeout.
    if isinstance(exc, TimeoutError):
        return HTTPException(
            status_code=504,
            detail={
                "code": "execution_timeout",
                "message": str(exc),
            },
        )

    # Gate's own fault, not the caller's and not the worker's: Gate minted a
    # packet that does not carry its routing authority, or its dispatch
    # transport is misconfigured. Both subclass ValueError, so they MUST be
    # matched before the generic ValueError branch below or a Gate bug is
    # reported to the caller as a 400 they cannot act on.
    if isinstance(exc, GateDispatchAuthorityError | GateDispatchConfigurationError):
        return HTTPException(
            status_code=500,
            detail={
                "code": "internal_error",
                "message": "internal server error",
            },
        )

    # An outbound security failure is Gate's (it could not sign); an inbound one
    # means the worker's answer could not be trusted, which is an upstream fault.
    if isinstance(exc, GateDispatchSecurityError):
        if exc.direction == "outbound":
            return HTTPException(
                status_code=500,
                detail={
                    "code": "internal_error",
                    "message": "internal server error",
                },
            )
        return HTTPException(
            status_code=502,
            detail={
                "code": "worker_response_untrusted",
                "message": str(exc),
                "node": getattr(exc, "node_name", None),
            },
        )

    # An upstream worker failing is not a Gate bug. Falling through to 500 hides
    # a dependency failure behind Gate's own error surface and sends an operator
    # to the wrong service. ``node`` is attribution the dispatcher attached: the
    # SDK is told a target, it never resolves one, so it cannot supply this.
    if isinstance(exc, GateDispatchError):
        return HTTPException(
            status_code=502,
            detail={
                "code": "worker_transport_failed",
                "message": str(exc),
                "node": getattr(exc, "node_name", None),
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
