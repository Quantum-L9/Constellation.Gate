"""The Gate->worker transport is closed to everything that is not a Gate dispatch.

``GateDispatchTransport`` is the only SDK surface that addresses a worker, so the
question that matters is not "can Gate reach a worker" but "can anything ELSE".
Importing the class grants nothing: the authority check is on the packet, and a
node cannot mint a packet that passes it.

Every rejection below is asserted to happen with ZERO network requests. A check
that fired after the POST would already have delivered the packet, so "rejected"
and "rejected before I/O" are different claims and only the second is worth
anything. The worker here is the real SDK runtime, so a packet that got through
would genuinely execute.

These are exercised against the SAME configuration Gate wires in production
(``get_gate_dispatch_config``-shaped), not a permissive test config.
"""

from __future__ import annotations

import pytest
from constellation_node_sdk.gate_authority import (
    GateDispatchAuthorityError,
    GateDispatchConfigurationError,
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


def _config() -> GateDispatchTransportConfig:
    return GateDispatchTransportConfig(local_gate_node=GATE)


def _gate_authored(**overrides) -> TransportPacket:
    """A genuine Gate-authored dispatch packet, before any override is applied."""
    fields: dict = {
        "action": "converge",
        "payload": {"opaque": True},
        "tenant": "tenant-a",
        "source_node": GATE,
        "destination_node": WORKER,
        "reply_to": GATE,
        "provenance": RoutingProvenance(
            origin_kind="gate",
            requested_action="converge",
            resolved_by_gate=True,
            route_kind="external_ingress",
            original_source_node="odoo",
        ),
    }
    fields.update(overrides)
    base = create_transport_packet(**fields)
    return base.with_hop(
        make_dispatch_hop(
            packet=base,
            node=base.address.source_node,
            action=base.header.action,
            target_node=base.address.destination_node,
            status="delegated",
        )
    )


async def _send(packet: TransportPacket, *, target_node: str = WORKER, url: str = WORKER_URL):
    worker = SdkWorker(node_name=WORKER, action="converge")
    async with worker.client() as client:
        transport = GateDispatchTransport(_config(), client=client)
        try:
            result = await transport.send_gate_authored_packet(
                packet=packet, target_node=target_node, worker_base_url=url
            )
        finally:
            # Returned on both paths: the request count is the assertion, and it
            # is only meaningful when it is read on the failure path too.
            _send.last_worker = worker  # type: ignore[attr-defined]
    return result


async def _expect_rejected_before_io(packet: TransportPacket, **kwargs) -> Exception:
    with pytest.raises(GateDispatchAuthorityError) as info:
        await _send(packet, **kwargs)

    worker: SdkWorker = _send.last_worker  # type: ignore[attr-defined]
    assert worker.request_count == 0, (
        "the packet was rejected only AFTER it had already been delivered to the "
        "worker; an authority check that fires post-POST is not a boundary"
    )
    return info.value


@pytest.mark.asyncio
async def test_a_genuine_gate_dispatch_is_accepted() -> None:
    """The control case: without it, every rejection below could be vacuous."""
    result = await _send(_gate_authored())

    worker: SdkWorker = _send.last_worker  # type: ignore[attr-defined]
    assert worker.request_count == 1
    assert result.address.source_node == WORKER
    assert result.address.destination_node == GATE


@pytest.mark.asyncio
async def test_a_packet_not_sourced_from_gate_is_rejected() -> None:
    await _expect_rejected_before_io(_gate_authored(source_node="odoo"))


@pytest.mark.asyncio
async def test_a_packet_addressed_elsewhere_is_rejected() -> None:
    """The named target and the packet's destination must be the same node."""
    packet = _gate_authored(destination_node="other-worker")
    await _expect_rejected_before_io(packet, target_node=WORKER)


@pytest.mark.asyncio
async def test_a_dispatch_that_does_not_reply_to_gate_is_rejected() -> None:
    await _expect_rejected_before_io(_gate_authored(reply_to="odoo"))


@pytest.mark.asyncio
async def test_a_packet_gate_did_not_resolve_is_rejected() -> None:
    await _expect_rejected_before_io(
        _gate_authored(
            provenance=RoutingProvenance(
                origin_kind="gate",
                requested_action="converge",
                resolved_by_gate=False,
                route_kind="external_ingress",
                original_source_node="odoo",
            )
        )
    )


@pytest.mark.asyncio
async def test_a_packet_without_route_kind_is_rejected() -> None:
    await _expect_rejected_before_io(
        _gate_authored(
            provenance=RoutingProvenance(
                origin_kind="gate",
                requested_action="converge",
                resolved_by_gate=True,
                original_source_node="odoo",
            )
        )
    )


@pytest.mark.asyncio
async def test_an_ordinary_node_packet_cannot_buy_peer_transport_with_a_url() -> None:
    """The headline claim: knowing a worker's URL is not authority to reach it.

    This is the packet an ordinary application holds -- node-origin, not resolved
    by Gate, addressed peer-to-peer. Supplying the worker's address alongside it
    must not turn it into a dispatch.
    """
    node_packet = create_transport_packet(
        action="converge",
        payload={"opaque": True},
        tenant="tenant-a",
        source_node="odoo",
        destination_node=WORKER,
        reply_to="odoo",
        provenance=RoutingProvenance(
            origin_kind="node",
            requested_action="converge",
            resolved_by_gate=False,
            original_source_node="odoo",
        ),
    )

    await _expect_rejected_before_io(node_packet)


@pytest.mark.asyncio
async def test_the_sdk_owns_the_execution_endpoint_not_the_caller() -> None:
    """Gate supplies a base URL from its registry; it does not choose the path."""
    for bad_url in (
        "http://eie:8000/v1/execute",
        "http://eie:8000/somewhere-else",
        "http://eie:8000?x=1",
        "ftp://eie:8000",
        "",
    ):
        with pytest.raises(GateDispatchConfigurationError):
            await _send(_gate_authored(), url=bad_url)

        worker: SdkWorker = _send.last_worker  # type: ignore[attr-defined]
        assert worker.request_count == 0, f"{bad_url!r} reached the network"
