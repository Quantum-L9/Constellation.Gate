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
    from constellation_node_sdk.gate_authority import WorkerConnectionError, WorkerHTTPError

    from constellation_gate.api.errors import to_http_exception

    unreachable = WorkerConnectionError("down")
    unreachable.node_name = "eie"
    mapped = to_http_exception(unreachable)
    assert mapped.status_code == 502
    assert mapped.detail["code"] == "worker_transport_failed"
    assert mapped.detail["node"] == "eie"

    bad_response = to_http_exception(WorkerHTTPError("HTTP 503", status_code=503))
    assert bad_response.status_code == 502


def test_worker_timeout_is_still_a_gateway_timeout() -> None:
    """The SDK's WorkerTimeoutError is also a TimeoutError; 504 wins."""
    from constellation_node_sdk.gate_authority import WorkerTimeoutError

    from constellation_gate.api.errors import to_http_exception

    mapped = to_http_exception(WorkerTimeoutError("no answer", timeout_seconds=2.0))
    assert mapped.status_code == 504
    assert mapped.detail["code"] == "execution_timeout"


def test_a_gate_authored_packet_defect_is_never_blamed_on_the_caller() -> None:
    """GateDispatchAuthorityError subclasses ValueError; it must not map to 400.

    It means Gate minted a packet that does not carry its own routing authority
    -- a Gate bug the caller can do nothing about. Falling through to the generic
    ValueError branch would report it as a client error and send whoever reads
    the response to the wrong service.
    """
    from constellation_node_sdk.gate_authority import (
        GateDispatchAuthorityError,
        GateDispatchConfigurationError,
    )

    from constellation_gate.api.errors import to_http_exception

    for exc in (
        GateDispatchAuthorityError("not a Gate dispatch"),
        GateDispatchConfigurationError("bad worker base url"),
    ):
        mapped = to_http_exception(exc)
        assert isinstance(exc, ValueError), "precondition: these are ValueErrors"
        assert mapped.status_code == 500, f"{type(exc).__name__} must not be a 4xx"
        assert mapped.detail["code"] == "internal_error"


def test_an_untrusted_worker_response_is_a_gateway_error_not_an_internal_one() -> None:
    """An inbound security failure is the worker's answer failing, not Gate failing."""
    from constellation_node_sdk.gate_authority import GateDispatchSecurityError

    from constellation_gate.api.errors import to_http_exception

    inbound = GateDispatchSecurityError("bad signature", direction="inbound")
    inbound.node_name = "eie"
    mapped = to_http_exception(inbound)
    assert mapped.status_code == 502
    assert mapped.detail["code"] == "worker_response_untrusted"
    assert mapped.detail["node"] == "eie"

    outbound = GateDispatchSecurityError("cannot sign", direction="outbound")
    assert to_http_exception(outbound).status_code == 500, (
        "Gate failing to sign its own dispatch is Gate's fault, not the worker's"
    )
