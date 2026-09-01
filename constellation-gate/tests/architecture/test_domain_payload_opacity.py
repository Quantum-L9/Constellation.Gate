"""ADR-GATE-003: Gate routes domain payloads; it never interprets or translates them.

Gate must not become a schema translator for the applications behind it. These
tests use payloads Gate has no vocabulary for -- deliberately including the exact
field names the enrichment domain uses -- and assert byte-for-byte preservation
through ingress, derivation, and worker dispatch.
"""

from __future__ import annotations

import asyncio
import copy

from constellation_node_sdk.transport.packet import TransportPacket, create_transport_packet
from constellation_node_sdk.transport.provenance import RoutingProvenance
from support.sdk_worker import SdkWorker

from constellation_gate.routing.dispatch import Dispatcher
from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry

# Field names that a translating Gate would be tempted to rewrite
# (status -> state, final_fields -> fields, entity_snapshot -> entity).
ADVERSARIAL_PAYLOAD = {
    "status": "incomplete",
    "final_fields": {"a": 1, "b": [2, 3]},
    "entity_snapshot": {"id": "e-1", "nested": {"deep": {"deeper": [None, True, 1.5]}}},
    "state": "should-not-be-rewritten",
    "fields": ["untouched"],
    "entity": {"kind": "opaque"},
    "provider_payload": {"weird key": "with spaces", "": "empty key"},
    "unicode": "é中文\U0001f600",
    "numbers": [0, -1, 1.0, 1e30],
    "explicit_null": None,
    "empty_containers": {"list": [], "dict": {}},
}


WORKER_RESULT = {"worker_owned": {"result": "opaque-to-gate"}}


def _worker_handler(org_id: str, payload: dict) -> dict:
    """A worker that answers with its OWN vocabulary, not the caller's.

    Returning something different from the request payload is what makes the
    response-direction assertions meaningful: an echo would pass even if Gate
    were quietly substituting the request payload for the worker's answer.
    """
    return WORKER_RESULT


def _dispatch_with(payload: dict) -> tuple[TransportPacket, TransportPacket]:
    """Dispatch through the real SDK worker; return (packet the worker got, answer).

    The worker is the SDK runtime rather than a capturing fake, so the packet
    inspected here is one that passed a real worker's ingress validation -- a
    payload Gate had corrupted would be rejected there rather than silently
    recorded.
    """
    registry = NodeRegistry()
    registry.register_node(
        "eie",
        NodeRegistration(
            node_name="eie",
            internal_url="http://eie:8000",
            supported_actions=("converge",),
            metadata={"owner": "eie"},
        ),
    )

    worker = SdkWorker(node_name="eie", action="converge", handler=_worker_handler)

    inbound = create_transport_packet(
        action="converge",
        payload=payload,
        tenant="tenant-a",
        destination_node="gate",
        source_node="odoo",
        reply_to="odoo",
        provenance=RoutingProvenance(
            origin_kind="node",
            requested_action="converge",
            resolved_by_gate=False,
            original_source_node="odoo",
        ),
    )

    async def run() -> TransportPacket:
        async with worker.client() as client:
            dispatcher = Dispatcher(local_node="gate", registry=registry, client=client)
            return await dispatcher.dispatch(inbound)

    result = asyncio.run(run())
    return worker.received_packets[0], result


def test_worker_packet_payload_is_identical_to_ingress_payload() -> None:
    original = copy.deepcopy(ADVERSARIAL_PAYLOAD)
    worker_packet, _ = _dispatch_with(copy.deepcopy(ADVERSARIAL_PAYLOAD))

    assert worker_packet.payload == original


def test_no_domain_field_is_renamed_added_or_dropped() -> None:
    worker_packet, _ = _dispatch_with(copy.deepcopy(ADVERSARIAL_PAYLOAD))
    worker_payload = worker_packet.payload

    assert set(worker_payload) == set(ADVERSARIAL_PAYLOAD)
    # The specific translations ADR-GATE-003 forbids.
    assert worker_payload["status"] == "incomplete"
    assert worker_payload["final_fields"] == ADVERSARIAL_PAYLOAD["final_fields"]
    assert worker_payload["entity_snapshot"] == ADVERSARIAL_PAYLOAD["entity_snapshot"]


def test_deeply_nested_structures_survive_derivation() -> None:
    worker_packet, _ = _dispatch_with(copy.deepcopy(ADVERSARIAL_PAYLOAD))
    worker_payload = worker_packet.payload

    assert worker_payload["entity_snapshot"]["nested"]["deep"]["deeper"] == [None, True, 1.5]


def test_gate_does_not_mutate_the_callers_payload_object() -> None:
    supplied = copy.deepcopy(ADVERSARIAL_PAYLOAD)
    _dispatch_with(supplied)

    assert supplied == ADVERSARIAL_PAYLOAD


def test_worker_response_payload_is_returned_untranslated() -> None:
    _, result = _dispatch_with(copy.deepcopy(ADVERSARIAL_PAYLOAD))

    assert result.payload == WORKER_RESULT


def test_payload_with_only_unknown_vocabulary_still_routes() -> None:
    """Gate must route a payload whose every key is meaningless to it."""
    alien = {"zzz": {"qqq": ["☃", {"1": 2}]}, "": None}
    worker_packet, _ = _dispatch_with(copy.deepcopy(alien))

    assert worker_packet.payload == alien
