"""ADR-GATE-015 / ADR-GATE-017: stale SDK transport incompatibility must fail closed.

Gate's own fixtures agreed with Gate, so two SDK-side transport defects rode the
pin invisibly until a round trip ran the REAL worker-side validators:

1. `derive()` carried parent hops into the child, whose packet_id no longer
   matched -> every Gate dispatch failed `validate_hop_trace` at the worker.
2. `_canonicalize` used local-TZ datetimes, making `transport_hash`
   machine-dependent (Mac EDT vs Docker UTC).

These assert the installed SDK still carries both fixes, so a pin rollback is a
loud test failure rather than a silent production incompatibility.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from constellation_node_sdk.transport import hashing
from constellation_node_sdk.transport.packet import TransportPacket, create_transport_packet

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def test_sdk_pin_is_an_exact_commit_not_a_floating_branch() -> None:
    text = PYPROJECT.read_text(encoding="utf-8")

    assert "Gate_SDK.git@main" not in text, "SDK must never float on main"
    assert "Gate_SDK.git@" in text

    pin = text.split("Gate_SDK.git@", 1)[1].split('"', 1)[0].strip()
    assert len(pin) == 40 and all(c in "0123456789abcdef" for c in pin), (
        f"SDK pin must be a full 40-char commit sha, got {pin!r}"
    )


def test_derive_does_not_carry_parent_hops_into_the_child() -> None:
    """A child packet must carry only hops bound to its own packet_id."""
    parent = create_transport_packet(
        action="converge",
        payload={"opaque": True},
        tenant="tenant-a",
        destination_node="gate",
        source_node="odoo",
        reply_to="odoo",
    )

    from constellation_node_sdk.transport.hop_trace import make_ingress_hop

    observed = parent.with_hop(
        make_ingress_hop(packet=parent, node="gate", action="converge", status="validated")
    )
    assert len(observed.hop_trace) == 1

    child = observed.derive(destination_node="eie", source_node="gate", reply_to="gate")

    assert child.hop_trace == ()
    assert child.lineage.parent_id == observed.header.packet_id


def test_every_hop_on_a_packet_is_bound_to_that_packet() -> None:
    """The invariant the worker enforces; assert it on Gate's own output."""
    from constellation_gate.routing.dispatch import Dispatcher  # noqa: F401  (import guard)

    parent = create_transport_packet(
        action="converge",
        payload={},
        tenant="tenant-a",
        destination_node="gate",
        source_node="odoo",
        reply_to="odoo",
    )
    child = parent.derive(destination_node="eie", source_node="gate", reply_to="gate")

    assert all(hop.packet_id == child.header.packet_id for hop in child.hop_trace)


def test_transport_hash_canonicalization_is_utc_stable() -> None:
    """A machine's local timezone must not change a packet's transport_hash."""
    source = inspect.getsource(hashing._canonicalize)

    assert "astimezone(UTC)" in source, (
        "SDK hashing must canonicalize datetimes to UTC; local-TZ conversion makes "
        "transport_hash machine-dependent and breaks Gate->worker integrity checks"
    )
    assert "datetime.now().astimezone().tzinfo" not in source


def test_route_kind_is_available_on_routing_provenance() -> None:
    """Canonical worker ingress requires route_kind; Gate must be able to set it."""
    from constellation_node_sdk.transport.provenance import RoutingProvenance

    provenance = RoutingProvenance(
        origin_kind="gate",
        requested_action="converge",
        resolved_by_gate=True,
        route_kind="external_ingress",
    )
    assert provenance.route_kind == "external_ingress"


def test_packet_model_round_trips_through_json() -> None:
    packet = create_transport_packet(
        action="converge",
        payload={"nested": {"a": [1, 2]}},
        tenant="tenant-a",
        destination_node="gate",
        source_node="odoo",
        reply_to="odoo",
    )

    assert TransportPacket.model_validate(packet.model_dump_json_dict()) == packet
