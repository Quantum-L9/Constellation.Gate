from __future__ import annotations

from fastapi import HTTPException

from constellation_gate.boundary.ingress_validator import IngressValidationError
from constellation_gate.boundary.routing_policy import RoutingPolicyError


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

    if isinstance(exc, TimeoutError):
        return HTTPException(
            status_code=504,
            detail={
                "code": "execution_timeout",
                "message": str(exc),
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
