"""The per-node concurrency limit is the authoritative admission gate.

The worker here is the real SDK runtime (``tests/support/sdk_worker``) held
mid-call, rather than a fake client: the point of the test is that a SECOND
dispatch is refused while a FIRST is genuinely in flight, and only a worker that
is really occupied demonstrates that.
"""

from __future__ import annotations

import asyncio

import pytest
from constellation_node_sdk.transport.packet import create_transport_packet
from constellation_node_sdk.transport.provenance import RoutingProvenance
from support.sdk_worker import SdkWorker

from constellation_gate.routing.dispatch import Dispatcher
from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry
from constellation_gate.runtime.node_limits import NodeLimitExceededError, PerNodeLimiterManager


def _packet(entity_id: str):
    return create_transport_packet(
        action="score",
        payload={"entity_id": entity_id},
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


@pytest.mark.asyncio
async def test_dispatch_enforces_per_node_concurrency_limit() -> None:
    registry = NodeRegistry()
    registry.register_node(
        "score",
        NodeRegistration(
            node_name="score",
            internal_url="http://score:8000",
            supported_actions=("score",),
            max_concurrent=1,
            timeout_ms=15_000,
        ),
    )

    worker = SdkWorker(node_name="score", action="score", blocking=True)
    node_limits = PerNodeLimiterManager()

    async with worker.client() as client:
        dispatcher = Dispatcher(
            local_node="gate",
            registry=registry,
            client=client,
            node_limits=node_limits,
        )

        first_task = asyncio.create_task(dispatcher.dispatch(_packet("42")))
        await worker.entered.wait()

        second = _packet("43")
        with pytest.raises(NodeLimitExceededError):
            await dispatcher.dispatch(second)

        worker.release.set()
        result = await first_task

    assert result.payload["entity_id"] == "42"
    assert worker.request_count == 1, "the rejected dispatch must not have reached the worker"
