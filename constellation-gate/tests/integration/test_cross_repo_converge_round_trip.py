"""Cross-repository executable contract: producer -> Gate -> SDK worker runtime.

The worker side here is the REAL Gate_SDK ingress validator
(`validate_execute_ingress_packet`) plus the real handler execution path -- not a
hand-rolled stand-in. That is the point: it proves Gate's derived child packet is
accepted by the same code an EIE worker runs, rather than by a fixture written to
agree with Gate.

What this does NOT prove: a live EIE process, or a deployed Gate. Those are
recorded as NOT_RUN in FINAL_FINDINGS.md rather than implied by this passing.
"""

from __future__ import annotations

import asyncio
import copy

import pytest
from constellation_node_sdk.runtime.handlers import clear_handlers, register_handler
from constellation_node_sdk.transport.packet import TransportPacket, create_transport_packet
from constellation_node_sdk.transport.provenance import RoutingProvenance
from support.sdk_worker import SdkWorker

from constellation_gate.boundary.ingress_validator import IngressValidator
from constellation_gate.routing.dispatch import Dispatcher
from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry

# The exact payload the live Odoo builder emits
# (IB-Odoo_19 plasticos_gate/services/gate_builders.py::build_converge_request).
# Gate has no vocabulary for any of it.
ODOO_PAYLOAD = {
    "entity": {
        "name": "Acme Recycling",
        "city": "Charlotte",
        "id": "res.partner:55",
        "_odoo_entity_id": "res.partner:55",
    },
    "object_type": "plasticos",
    "objective": "Full entity enrichment and inference",
    "max_variations": 5,
    "idempotency_key": "odoo:enrichment:plasticos:plasticos.enrichment.run:7",
    "odoo": {
        "model": "plasticos.enrichment.run",
        "record_id": 7,
        "company_id": 1,
        "user_id": 2,
        "db_name": "plasticos",
        "correlation_id": "plasticos.enrichment.run:7",
    },
}

# The exact answer shape EIE's converge handler returns (EnrichResponse).
WORKER_RESULT = {
    "state": "completed",
    "failure_reason": None,
    "fields": {"website": "https://example.test"},
    "confidence": 0.91,
    "provider_trace": [{"provider": "vies", "hit": True}],
}


@pytest.fixture(autouse=True)
def _clean_handlers():
    clear_handlers()
    yield
    clear_handlers()


def _gate_stack() -> tuple[IngressValidator, NodeRegistry, SdkWorker]:
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
    # The worker applies the SDK's real /v1/execute ingress policy and the real
    # handler execution path; only the socket is substituted.
    worker = SdkWorker(node_name="eie", action="converge", gate_node_name="gate")
    validator = IngressValidator(
        local_node="gate",
        known_nodes_provider=lambda: {"eie", "odoo"},
    )
    return validator, registry, worker


def _root_packet(*, idempotency_key: str | None = "odoo-req-1") -> TransportPacket:
    return create_transport_packet(
        action="converge",
        payload=copy.deepcopy(ODOO_PAYLOAD),
        tenant={"org_id": "scrapmanagement", "actor": "odoo", "originator": "odoo"},
        destination_node="gate",
        source_node="odoo",
        reply_to="odoo",
        idempotency_key=idempotency_key,
        correlation_id="corr-abc",
        provenance=RoutingProvenance(
            origin_kind="node",
            requested_action="converge",
            resolved_by_gate=False,
            original_source_node="odoo",
        ),
    )


def _run_round_trip():
    validator, registry, worker = _gate_stack()

    register_handler("converge", lambda packet: dict(WORKER_RESULT))

    root = _root_packet()
    validated = validator.validate(root.model_dump_json_dict())

    async def run() -> TransportPacket:
        async with worker.client() as client:
            dispatcher = Dispatcher(local_node="gate", registry=registry, client=client)
            return await dispatcher.dispatch(validated)

    result = asyncio.run(run())
    return root, worker, result


def test_gate_derived_packet_passes_real_sdk_worker_ingress() -> None:
    _, worker, _ = _run_round_trip()

    assert worker.ingress_errors == []
    assert len(worker.received_packets) == 1


def test_worker_packet_lineage_and_addressing_are_canonical() -> None:
    root, worker, _ = _run_round_trip()
    worker_packet = worker.received_packets[0]

    assert worker_packet.header.packet_id != root.header.packet_id
    assert worker_packet.lineage.parent_id == root.header.packet_id
    assert worker_packet.lineage.root_id == root.lineage.root_id
    assert worker_packet.address.source_node == "gate"
    assert worker_packet.address.destination_node == "eie"
    assert worker_packet.address.reply_to == "gate"
    assert worker_packet.provenance.origin_kind == "gate"
    assert worker_packet.provenance.resolved_by_gate is True
    assert worker_packet.provenance.original_source_node == "odoo"


def test_tenant_context_is_preserved_across_the_hop() -> None:
    root, worker, _ = _run_round_trip()

    assert worker.received_packets[0].tenant == root.tenant
    assert worker.received_packets[0].tenant.org_id == "scrapmanagement"


def test_domain_payload_crosses_gate_unchanged() -> None:
    _, worker, _ = _run_round_trip()

    assert worker.received_packets[0].payload == ODOO_PAYLOAD


def test_worker_response_is_validated_and_returned_untranslated() -> None:
    _, _, result = _run_round_trip()

    assert isinstance(result, TransportPacket)
    assert result.payload == WORKER_RESULT
    # Gate did not translate the worker's dialect: state/fields ride as-is.
    assert result.payload["state"] == "completed"
    assert result.payload["fields"] == {"website": "https://example.test"}
    assert "status" not in result.payload
    assert "final_fields" not in result.payload


def test_dispatch_hop_is_recorded_against_the_derived_packet() -> None:
    _, worker, _ = _run_round_trip()
    worker_packet = worker.received_packets[0]

    dispatch_hops = [hop for hop in worker_packet.hop_trace if hop.direction == "dispatch"]
    assert len(dispatch_hops) == 1
    assert dispatch_hops[0].target_node == "eie"
    assert dispatch_hops[0].packet_id == worker_packet.header.packet_id


def test_converge_is_routable_to_an_eie_owned_node_and_dispatches_through_the_sdk() -> None:
    """Readiness and dispatch are the same claim, so prove them together.

    ``action_routability`` reporting converge routable is a registry-level
    statement; it says nothing about whether a packet actually reaches the node.
    Asserting both against one registry is what makes "converge is routable to
    EIE" mean the thing an operator reads it as.

    The worker here is an SDK-backed stand-in, NOT a live EIE process. That
    distinction is recorded as ``real_eie: NOT_RUN`` in FINAL_FINDINGS.md rather
    than implied by this passing.
    """
    from constellation_gate.runtime.routing_readiness import action_routability

    validator, registry, worker = _gate_stack()
    register_handler("converge", lambda packet: dict(WORKER_RESULT))

    readiness = action_routability(registry, "converge")
    assert readiness["routable"] is True
    assert readiness["required_owner"] == "eie"

    validated = validator.validate(_root_packet().model_dump_json_dict())

    async def run() -> TransportPacket:
        async with worker.client() as client:
            dispatcher = Dispatcher(local_node="gate", registry=registry, client=client)
            return await dispatcher.dispatch(validated)

    result = asyncio.run(run())

    assert worker.ingress_errors == []
    assert worker.received_packets[0].address.destination_node == "eie"
    assert result.payload == WORKER_RESULT
