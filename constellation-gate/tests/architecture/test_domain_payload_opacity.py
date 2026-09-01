"""Gate must never interpret an application's domain payload.

Two complementary guards:

1. A static scan: Gate production code must not name domain concepts. This
   catches translation being *added*, at the moment it is added, rather than
   after it has grown consumers.
2. A behavioral proof: an arbitrary nested payload must survive ingress ->
   observation hop -> derive -> the packet actually handed to worker transport,
   byte-for-byte after JSON round-trip.

The static scan alone would be theater (a domain field can be read via a
variable), and the behavioral proof alone would pass while translation sat in a
branch the fixture never exercises. Together they bound the failure.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
from constellation_node_sdk.transport.packet import TransportPacket, create_transport_packet

from constellation_gate.resilience.deadline import PacketDeadline
from constellation_gate.routing.dispatch import Dispatcher
from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "constellation_gate"

# Application-domain vocabulary. Gate routes packets; it has no business naming
# any of these. Deliberately excludes generic routing words ("status", "state")
# that legitimately describe hop/circuit state.
FORBIDDEN_DOMAIN_IDENTIFIERS = frozenset(
    {
        "entity",
        "entity_snapshot",
        "enrichrequest",
        "enrichresponse",
        "final_fields",
        "writeback",
        "odoo",
        "crm",
        "supplier",
        "material_profile",
    }
)


def _production_modules() -> list[Path]:
    return sorted(p for p in SRC_ROOT.rglob("*.py") if "egg-info" not in str(p))


def test_no_domain_identifiers_in_gate_production_code() -> None:
    """No Gate module may name an application-domain concept."""
    offenders: list[str] = []

    for module in _production_modules():
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Name):
                names.append(node.id)
            elif isinstance(node, ast.Attribute):
                names.append(node.attr)
            elif isinstance(node, ast.arg):
                names.append(node.arg)
            elif isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                names.append(node.name)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                # A string literal is how a payload key would actually be read.
                names.append(node.value)

            for name in names:
                if name.strip().lower() in FORBIDDEN_DOMAIN_IDENTIFIERS:
                    offenders.append(f"{module.relative_to(SRC_ROOT)}: {name!r}")

    assert not offenders, (
        "Gate production code references application-domain concepts. "
        "Payloads are opaque to the router:\n  " + "\n  ".join(offenders)
    )


class _CapturingTransport:
    """Stands in for the worker; records exactly what transport was handed."""

    def __init__(self) -> None:
        self.dispatched: TransportPacket | None = None

    async def post(self, url: str, json: dict[str, Any], headers: dict[str, str], timeout: float):
        from httpx import Request, Response

        self.dispatched = TransportPacket.model_validate(json)
        response_packet = create_transport_packet(
            action=json["header"]["action"],
            payload={"echo": True},
            tenant="tenant-a",
            destination_node="gate",
            source_node="worker",
            reply_to="gate",
        )
        return Response(
            status_code=200,
            json=response_packet.model_dump_json_dict(),
            request=Request("POST", url),
        )


ADVERSARIAL_PAYLOADS: list[dict[str, Any]] = [
    {"entity": {"id": 7, "fields": {"status": "draft"}}, "final_fields": ["a", "b"]},
    {"": "empty-key", "nested": {"deep": {"deeper": [1, {"x": None}, True]}}},
    {"unicode": "é中文\U0001f600", "sep": "a\x1fb", "quote": 'say "hi"'},
    {"numbers": [0, -1, 2**53, 1.5, 0.0]},
    {"nulls": None, "false": False, "zero": 0, "empty_list": [], "empty_obj": {}},
    {"writeback": {"odoo": {"crm": "should be untouched"}}},
]


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", ADVERSARIAL_PAYLOADS)
async def test_payload_survives_dispatch_byte_for_byte(payload: dict[str, Any]) -> None:
    """child.payload == ingress.payload through observation, derive, transport."""
    registry = NodeRegistry()
    registry.register_node(
        "worker",
        NodeRegistration(
            node_name="worker",
            internal_url="http://worker:8000",
            supported_actions=("score",),
            timeout_ms=30_000,
        ),
    )

    transport = _CapturingTransport()
    dispatcher = Dispatcher(local_node="gate", registry=registry, client=transport)

    ingress = create_transport_packet(
        action="score",
        payload=payload,
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )

    await dispatcher.dispatch(ingress, deadline=PacketDeadline(30.0))

    assert transport.dispatched is not None
    assert transport.dispatched.payload == ingress.payload
    # Hash equality proves nothing was reordered, coerced, or re-typed either.
    assert transport.dispatched.security.payload_hash == ingress.security.payload_hash


@pytest.mark.asyncio
async def test_dispatch_does_not_mutate_the_ingress_payload_object() -> None:
    """Gate must not reach into the caller's payload dict in place."""
    registry = NodeRegistry()
    registry.register_node(
        "worker",
        NodeRegistration(
            node_name="worker",
            internal_url="http://worker:8000",
            supported_actions=("score",),
        ),
    )
    payload = {"entity": {"id": 1}, "keep": [1, 2, 3]}
    snapshot = {"entity": {"id": 1}, "keep": [1, 2, 3]}

    ingress = create_transport_packet(
        action="score",
        payload=payload,
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )
    dispatcher = Dispatcher(local_node="gate", registry=registry, client=_CapturingTransport())
    await dispatcher.dispatch(ingress, deadline=PacketDeadline(30.0))

    assert payload == snapshot
