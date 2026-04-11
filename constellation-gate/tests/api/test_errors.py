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
