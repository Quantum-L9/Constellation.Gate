"""The Gate->worker rail under signatures, in both directions.

An unsigned round trip proves addressing. It does not prove that a tampered
packet is refused, which is the only property signing exists for. So each leg is
exercised twice: once intact, once altered in flight by a transport that sits
between Gate and the worker and edits the bytes.

Both directions matter and fail for different reasons:

* Gate signs the dispatch; the worker verifies it. An attacker who can reach the
  worker's socket must not be able to forge a Gate dispatch.
* The worker signs its response; Gate verifies it. An answer Gate cannot
  authenticate is an inbound SECURITY failure, never a parsing failure it might
  reasonably retry into.
"""

from __future__ import annotations

import json

import httpx
import pytest
from constellation_node_sdk.gate_authority import (
    GateDispatchSecurityError,
    GateDispatchTransport,
    GateDispatchTransportConfig,
)
from constellation_node_sdk.transport.hop_trace import make_dispatch_hop
from constellation_node_sdk.transport.packet import TransportPacket, create_transport_packet
from constellation_node_sdk.transport.provenance import RoutingProvenance
from support.sdk_worker import SdkWorker

GATE = "gate"
WORKER = "eie"
WORKER_URL = "http://eie:8000"

ALGORITHM = "hmac-sha256"
GATE_KEY_ID = "gate-key-1"
GATE_KEY = "gate-shared-secret-value"
WORKER_KEY_ID = "eie-key-1"
WORKER_KEY = "eie-shared-secret-value"

# Each side verifies the other's key as well as recognising its own.
KEYRING = {GATE_KEY_ID: GATE_KEY, WORKER_KEY_ID: WORKER_KEY}


def _gate_config(**overrides) -> GateDispatchTransportConfig:
    fields: dict = {
        "local_gate_node": GATE,
        "require_signature": True,
        "signing_key": GATE_KEY,
        "signing_key_id": GATE_KEY_ID,
        "signing_algorithm": ALGORITHM,
        "verify_response_signatures": True,
        "verifying_keys": dict(KEYRING),
    }
    fields.update(overrides)
    return GateDispatchTransportConfig(**fields)


def _signing_worker(**overrides) -> SdkWorker:
    fields: dict = {
        "node_name": WORKER,
        "action": "converge",
        "gate_node_name": GATE,
        "require_signature": True,
        "signing_key": WORKER_KEY,
        "signing_key_id": WORKER_KEY_ID,
        "signing_algorithm": ALGORITHM,
        "verifying_keys": dict(KEYRING),
        "handler": lambda org_id, payload: {"result": "signed-ok"},
    }
    fields.update(overrides)
    return SdkWorker(**fields)


def _dispatch_packet() -> TransportPacket:
    base = create_transport_packet(
        action="converge",
        payload={"opaque": True},
        tenant="tenant-a",
        source_node=GATE,
        destination_node=WORKER,
        reply_to=GATE,
        provenance=RoutingProvenance(
            origin_kind="gate",
            requested_action="converge",
            resolved_by_gate=True,
            route_kind="external_ingress",
            original_source_node="odoo",
        ),
    )
    return base.with_hop(
        make_dispatch_hop(
            packet=base,
            node=GATE,
            action=base.header.action,
            target_node=WORKER,
            status="delegated",
        )
    )


class TamperingTransport(httpx.AsyncBaseTransport):
    """A man in the middle that edits the request, the response, or both."""

    def __init__(self, inner: httpx.AsyncBaseTransport, *, on_request=None, on_response=None):
        self._inner = inner
        self._on_request = on_request
        self._on_response = on_response

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self._on_request is not None:
            body = json.loads(request.content.decode("utf-8"))
            request = httpx.Request(
                request.method,
                request.url,
                headers={"Content-Type": "application/json"},
                json=self._on_request(body),
                extensions=request.extensions,
            )

        response = await self._inner.handle_async_request(request)
        if self._on_response is None:
            return response

        await response.aread()
        body = json.loads(response.content.decode("utf-8"))
        return httpx.Response(
            status_code=response.status_code,
            json=self._on_response(body),
            request=request,
        )


async def _round_trip(worker: SdkWorker, *, config=None, on_request=None, on_response=None):
    transport = TamperingTransport(
        worker.transport(), on_request=on_request, on_response=on_response
    )
    async with httpx.AsyncClient(transport=transport) as client:
        dispatch = GateDispatchTransport(config or _gate_config(), client=client)
        return await dispatch.send_gate_authored_packet(
            packet=_dispatch_packet(), target_node=WORKER, worker_base_url=WORKER_URL
        )


@pytest.mark.asyncio
async def test_a_signed_dispatch_round_trips_and_the_response_is_verified() -> None:
    worker = _signing_worker()

    result = await _round_trip(worker)

    assert worker.ingress_errors == [], "the worker rejected Gate's signed dispatch"
    assert worker.request_count == 1
    assert result.payload == {"result": "signed-ok"}
    assert result.address.source_node == WORKER
    assert result.address.destination_node == GATE
    # The dispatch really was signed, rather than passing because verification
    # was quietly disabled on one side.
    assert worker.received_packets[0].security.signature is not None
    assert result.security.signature is not None


@pytest.mark.asyncio
async def test_the_worker_refuses_a_dispatch_tampered_with_in_flight() -> None:
    worker = _signing_worker()

    def alter_payload(body: dict) -> dict:
        body["payload"] = {"opaque": False, "injected": True}
        return body

    with pytest.raises(Exception) as info:
        await _round_trip(worker, on_request=alter_payload)

    assert not isinstance(info.value, AssertionError)
    # The tampered body did reach the worker's socket...
    assert worker.request_count == 1
    # ...and was refused at canonical decode, BEFORE ingress policy or the
    # handler ran. Packet integrity is checked while the packet is being built,
    # so a mutated body never becomes a TransportPacket the worker could act on.
    assert worker.received_packets == [], (
        "the worker accepted a tampered body as a canonical packet"
    )
    assert worker.ingress_errors == [], "rejection should precede ingress policy, not depend on it"
    assert "signed-ok" not in str(info.value), "the tampered work was executed"


@pytest.mark.asyncio
async def test_gate_refuses_a_response_tampered_with_in_flight() -> None:
    worker = _signing_worker()

    def alter_payload(body: dict) -> dict:
        body["payload"] = {"result": "substituted"}
        return body

    with pytest.raises(GateDispatchSecurityError) as info:
        await _round_trip(worker, on_response=alter_payload)

    assert info.value.direction == "inbound", (
        "a forged worker answer must be an inbound SECURITY failure, not a "
        "parsing failure Gate might retry into"
    )


@pytest.mark.asyncio
async def test_gate_refuses_a_response_signed_by_an_unknown_key() -> None:
    """A perfectly valid signature from a key Gate does not trust is still a forgery."""
    worker = _signing_worker(
        signing_key="an-entirely-different-secret",
        signing_key_id="unknown-key-99",
        verifying_keys={**KEYRING, "unknown-key-99": "an-entirely-different-secret"},
    )

    with pytest.raises(GateDispatchSecurityError) as info:
        await _round_trip(worker)

    assert info.value.direction == "inbound"


@pytest.mark.asyncio
async def test_gate_refuses_a_response_signed_by_the_wrong_known_signer() -> None:
    """A key Gate DOES trust, used by the wrong party, must not authenticate."""
    worker = _signing_worker(
        signing_key="not-the-real-eie-secret",
        signing_key_id=WORKER_KEY_ID,
    )

    with pytest.raises(GateDispatchSecurityError) as info:
        await _round_trip(worker)

    assert info.value.direction == "inbound"


@pytest.mark.asyncio
async def test_gate_cannot_dispatch_when_it_cannot_sign() -> None:
    """A misconfigured signing setup must fail closed, never dispatch unsigned."""
    worker = _signing_worker()

    with pytest.raises(Exception) as info:
        await _round_trip(
            worker,
            config=_gate_config(signing_key_id=None, signing_algorithm=None),
        )

    assert worker.request_count == 0, "an unsignable dispatch still reached the worker"
    assert not isinstance(info.value, AssertionError)
