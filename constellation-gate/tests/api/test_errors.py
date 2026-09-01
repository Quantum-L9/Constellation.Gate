from __future__ import annotations

from constellation_gate.api.errors import to_http_exception
from constellation_gate.boundary.ingress_validator import IngressValidationError
from constellation_gate.boundary.routing_policy import RoutingPolicyError


def test_to_http_exception_maps_ingress_validation_error() -> None:
    exc = to_http_exception(IngressValidationError("bad packet"))

    assert exc.status_code == 400
    assert exc.detail["code"] == "invalid_transport_packet"
    assert exc.detail["message"] == "bad packet"


def test_to_http_exception_maps_routing_policy_error() -> None:
    exc = to_http_exception(RoutingPolicyError("forbidden route"))

    assert exc.status_code == 403
    assert exc.detail["code"] == "routing_policy_violation"


def test_to_http_exception_maps_permission_and_timeout_and_default() -> None:
    permission = to_http_exception(PermissionError("denied"))
    timeout = to_http_exception(TimeoutError("too slow"))
    unknown = to_http_exception(RuntimeError("boom"))

    assert permission.status_code == 401
    assert permission.detail["code"] == "admin_auth_failed"
    assert timeout.status_code == 504
    assert timeout.detail["code"] == "execution_timeout"
    assert unknown.status_code == 500
    assert unknown.detail["code"] == "internal_error"


def test_worker_transport_failure_is_reported_as_a_gateway_error() -> None:
    """An upstream worker failure must not masquerade as a Gate internal error."""
    from constellation_gate.api.errors import to_http_exception
    from constellation_gate.routing.worker_transport import (
        WorkerResponseError,
        WorkerUnreachableError,
    )

    unreachable = to_http_exception(WorkerUnreachableError("down", node_name="eie"))
    assert unreachable.status_code == 502
    assert unreachable.detail["code"] == "worker_transport_failed"
    assert unreachable.detail["node"] == "eie"

    bad_response = to_http_exception(
        WorkerResponseError("HTTP 503", node_name="eie", status_code=503)
    )
    assert bad_response.status_code == 502


def test_worker_timeout_is_still_a_gateway_timeout() -> None:
    """WorkerTimeoutError is both a transport error and a TimeoutError; 504 wins."""
    from constellation_gate.api.errors import to_http_exception
    from constellation_gate.routing.worker_transport import WorkerTimeoutError

    mapped = to_http_exception(WorkerTimeoutError("no answer", node_name="eie"))
    assert mapped.status_code == 504
    assert mapped.detail["code"] == "execution_timeout"
