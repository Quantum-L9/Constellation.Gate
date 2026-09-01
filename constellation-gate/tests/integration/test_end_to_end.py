from __future__ import annotations

import pytest
from constellation_node_sdk.transport.packet import create_transport_packet
from constellation_node_sdk.transport.provenance import RoutingProvenance
from support.sdk_worker import SdkWorker

from constellation_gate.boundary.ingress_validator import IngressValidator
from constellation_gate.orchestration.workflow_engine import WorkflowEngine
from constellation_gate.routing.dispatch import Dispatcher
from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry
from constellation_gate.services.execute_service import ExecuteService


@pytest.mark.asyncio
async def test_end_to_end_node_to_gate_to_worker_response_path() -> None:
    registry = NodeRegistry()
    registry.register_node(
        "score",
        NodeRegistration(
            node_name="score",
            internal_url="http://score:8000",
            supported_actions=("score",),
            timeout_ms=15_000,
        ),
    )

    worker = SdkWorker(
        node_name="score",
        action="score",
        gate_node_name="gate",
        handler=lambda org_id, payload: {"status": "completed", "score": 91},
    )

    validator = IngressValidator(
        local_node="gate",
        known_nodes_provider=registry.known_nodes,
    )

    request_packet = create_transport_packet(
        action="score",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="orchestrator",
        reply_to="orchestrator",
        provenance=RoutingProvenance(
            origin_kind="node",
            requested_action="score",
            resolved_by_gate=False,
            original_source_node="orchestrator",
        ),
    )

    async with worker.client() as client:
        dispatcher = Dispatcher(local_node="gate", registry=registry, client=client)
        workflow_engine = WorkflowEngine(definitions={}, dispatcher=dispatcher, local_node="gate")
        service = ExecuteService(
            local_node="gate",
            ingress_validator=validator,
            dispatcher=dispatcher,
            workflow_engine=workflow_engine,
            registry=registry,
        )
        response = await service.execute(request_packet.model_dump_json_dict())

    assert response.payload["status"] == "completed"
    assert response.payload["score"] == 91
    assert worker.request_count == 1
    assert worker.ingress_errors == []

    posted_packet = worker.received_packets[0]
    assert posted_packet.address.source_node == "gate"
    assert posted_packet.address.destination_node == "score"
    assert posted_packet.provenance.origin_kind == "gate"
    assert posted_packet.provenance.resolved_by_gate is True
