"""Executable cross-repository contract: Odoo-shaped root packet -> Gate -> EIE.

Chain under test:

    Odoo-compatible root TransportPacket
    -> Gate ingress
    -> action=converge, owner=eie
    -> resolver
    -> Gate-authored child packet
    -> worker transport
    -> SDK runtime validation at the worker (the same validate_transport_packet
       an EIE process runs on inbound)
    -> canonical response packet
    -> Gate response validation

The worker end is the SDK's own runtime validation, not a hand-rolled stub, so
this proves the packet Gate emits is one a real SDK node would accept. It is a
`sdk_worker_runtime_fixture`, NOT a live EIE process -- see FINAL_FINDINGS.md.
"""

from __future__ import annotations

from typing import Any

import pytest
from constellation_node_sdk.security.validation import validate_transport_packet
from constellation_node_sdk.transport.packet import TransportPacket, create_transport_packet

from constellation_gate.boundary.ingress_validator import IngressValidator
from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry
from constellation_gate.services.execute_service import ExecuteService

GATE_NODE = "gate"
EIE_NODE = "enrichment-engine"

# The exact payload shape Odoo sends for converge. Gate must not read any of it.
ODOO_CONVERGE_PAYLOAD: dict[str, Any] = {
    "entity": {
        "id": 4711,
        "name": "Acme Polymers GmbH",
        "fields": {"vat": None, "website": "https://example.invalid"},
    },
    "mode": "standard",
    "requested_fields": ["vat", "website", "phone"],
    "writeback": {"target": "odoo", "model": "res.partner"},
}


class SdkRuntimeWorker:
    """Worker end that runs the SDK's real inbound validation.

    Whatever Gate emits must survive the same check an EIE node applies.
    """

    def __init__(self) -> None:
        self.received: TransportPacket | None = None
        self.validation_error: Exception | None = None

    async def post(self, url: str, json: dict[str, Any], headers: dict[str, str], timeout: float):
        from httpx import Request, Response

        inbound = TransportPacket.model_validate(json)
        # This is the SDK runtime check an EIE process performs on ingress.
        validate_transport_packet(
            inbound,
            local_node=EIE_NODE,
            require_signature=False,
            dev_mode=True,
        )
        self.received = inbound

        response_packet = inbound.derive(
            packet_type="response",
            source_node=EIE_NODE,
            destination_node=inbound.address.reply_to,
            reply_to=EIE_NODE,
            payload={"status": "converged", "confidence": 0.91},
        )
        return Response(
            status_code=200,
            json=response_packet.model_dump_json_dict(),
            request=Request("POST", url),
        )


def _registry() -> NodeRegistry:
    registry = NodeRegistry()
    registry.register_node(
        EIE_NODE,
        NodeRegistration(
            node_name=EIE_NODE,
            internal_url="http://enrichment-engine:8000",
            supported_actions=("converge", "graph-inference-result", "enrich", "enrich-and-sync"),
            health_endpoint="/api/v1/health",
            timeout_ms=30_000,
            metadata={"owner": "eie", "version": "2.3.0", "type": "enrichment"},
        ),
    )
    return registry


class NoWorkflows:
    def has_workflow(self, action: str) -> bool:
        return False

    async def execute(self, packet: TransportPacket, *, deadline: Any = None) -> TransportPacket:
        raise AssertionError("converge must dispatch directly, not via a workflow")


def _odoo_root_packet(*, idempotency_key: str | None = "odoo-req-4711") -> TransportPacket:
    return create_transport_packet(
        action="converge",
        payload=ODOO_CONVERGE_PAYLOAD,
        tenant={"org_id": "acme-gmbh", "actor": "odoo", "user_id": "u-7"},
        destination_node=GATE_NODE,
        source_node="client",
        reply_to="client",
        idempotency_key=idempotency_key,
        timeout_ms=30_000,
    )


@pytest.fixture
def wired() -> tuple[ExecuteService, SdkRuntimeWorker]:
    from constellation_gate.routing.dispatch import Dispatcher

    registry = _registry()
    worker = SdkRuntimeWorker()
    dispatcher = Dispatcher(local_node=GATE_NODE, registry=registry, client=worker)
    service = ExecuteService(
        local_node=GATE_NODE,
        ingress_validator=IngressValidator(
            local_node=GATE_NODE,
            known_nodes_provider=registry.known_nodes,
            dev_mode=True,
        ),
        dispatcher=dispatcher,
        workflow_engine=NoWorkflows(),
        registry=registry,
    )
    return service, worker


@pytest.mark.asyncio
async def test_converge_round_trip_preserves_the_full_canonical_contract(
    wired: tuple[ExecuteService, SdkRuntimeWorker],
) -> None:
    service, worker = wired
    root = _odoo_root_packet()

    response = await service.execute(root.model_dump_json_dict())

    child = worker.received
    assert child is not None, "the SDK-validating worker must have been reached"

    # -- opaque payload preservation
    assert child.payload == root.payload
    assert child.security.payload_hash == root.security.payload_hash

    # -- tenant immutability
    assert child.tenant == root.tenant
    assert child.tenant.org_id == "acme-gmbh"

    # -- action and routing
    assert child.header.action == "converge"
    assert child.address.source_node == GATE_NODE
    assert child.address.destination_node == EIE_NODE
    assert child.address.reply_to == GATE_NODE
    assert child.provenance.origin_kind == "gate"
    assert child.provenance.resolved_by_gate is True
    assert child.provenance.original_source_node == "client"

    # -- lineage / causation
    assert child.header.packet_id != root.header.packet_id
    assert child.lineage.parent_id == root.header.packet_id
    assert child.lineage.root_id == root.lineage.root_id
    assert child.lineage.generation == root.lineage.generation + 1
    assert child.header.correlation_id == root.header.correlation_id
    assert child.header.idempotency_key == root.header.idempotency_key

    # -- hop correctness: the dispatch hop binds to the CHILD, and the parent's
    #    ingress hop is not illegally inherited.
    assert child.hop_trace, "the dispatch hop must be present on the child"
    assert all(hop.packet_id == child.header.packet_id for hop in child.hop_trace)

    # -- transport integrity holds after derive + hop
    assert child.security.transport_hash

    # -- Gate returns a canonical response packet
    assert isinstance(response, TransportPacket)
    assert response.payload["status"] == "converged"


@pytest.mark.asyncio
async def test_converge_is_dispatched_exactly_once(
    wired: tuple[ExecuteService, SdkRuntimeWorker],
) -> None:
    """No Gate-level whole-operation retry on the canonical converge path."""
    service, _ = wired

    class CountingWorker(SdkRuntimeWorker):
        calls = 0

        async def post(self, url, json, headers, timeout):  # type: ignore[no-untyped-def]
            type(self).calls += 1
            return await super().post(url, json, headers, timeout)

    counting = CountingWorker()
    service.dispatcher._client = counting  # noqa: SLF001 -- deliberate seam swap

    root = _odoo_root_packet(idempotency_key="odoo-req-single")
    await service.execute(root.model_dump_json_dict())
    assert CountingWorker.calls == 1


@pytest.mark.asyncio
async def test_gate_never_reads_the_domain_payload(
    wired: tuple[ExecuteService, SdkRuntimeWorker],
) -> None:
    """Nonsense in the domain payload must not change routing behavior."""
    service, worker = wired

    hostile_payload = {
        "action": "match",  # must NOT override header.action
        "tenant": {"org_id": "attacker"},  # must NOT override canonical tenant
        "destination_node": "somewhere-else",  # must NOT override routing
        "__proto__": {"x": 1},
    }
    root = create_transport_packet(
        action="converge",
        payload=hostile_payload,
        tenant={"org_id": "acme-gmbh", "actor": "odoo"},
        destination_node=GATE_NODE,
        source_node="client",
        reply_to="client",
        timeout_ms=30_000,
    )

    await service.execute(root.model_dump_json_dict())

    child = worker.received
    assert child is not None
    assert child.header.action == "converge"
    assert child.address.destination_node == EIE_NODE
    assert child.tenant.org_id == "acme-gmbh"
    assert child.payload == hostile_payload
