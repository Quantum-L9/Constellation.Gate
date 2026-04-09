from __future__ import annotations

import httpx
import pytest

from constellation_gate.boundary.ingress_validator import IngressValidator
from constellation_gate.orchestration.workflow_engine import WorkflowEngine
from constellation_gate.routing.dispatch import Dispatcher
from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry
from constellation_gate.services.execute_service import ExecuteService
from constellation_node_sdk.transport.packet import TransportPacket, create_transport_packet
from constellation_node_sdk.transport.provenance import RoutingProvenance


class FakeWorkerClient:
    def __init__(self, response_body: dict) -> None:
        self.response_body = response_body
        self.calls: list[dict] = []

    async def post(self, url: str, json: dict, headers: dict, timeout: float) -> httpx.Response:
        self.calls.append(
            {
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": timeout,
            }
        )
        request = httpx.Request("POST", url)
        return httpx.Response(status_code=200, json=self.response_body, request=request)


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

    worker_response = create_transport_packet(
        action="score",
        payload={"status": "completed", "score": 91},
        tenant="tenant-a",
        destination_node="gate",
        source_node="score",
        reply_to="gate",
    )
    fake_client = FakeWorkerClient(worker_response.model_dump_json_dict())

    validator = IngressValidator(
        local_node="gate",
        known_nodes_provider=registry.known_nodes,
    )
    dispatcher = Dispatcher(local_node="gate", registry=registry, client=fake_client)
    workflow_engine = WorkflowEngine(definitions={}, dispatcher=dispatcher, local_node="gate")
    service = ExecuteService(
        local_node="gate",
        ingress_validator=validator,
        dispatcher=dispatcher,
        workflow_engine=workflow_engine,
        registry=registry,
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

    response = await service.execute(request_packet.model_dump_json_dict())

    assert response.payload["status"] == "completed"
    assert response.payload["score"] == 91
    assert len(fake_client.calls) == 1

    posted_packet = TransportPacket.model_validate(fake_client.calls[0]["json"])
    assert posted_packet.address.source_node == "gate"
    assert posted_packet.address.destination_node == "score"
    assert posted_packet.provenance.origin_kind == "gate"
    assert posted_packet.provenance.resolved_by_gate is True
