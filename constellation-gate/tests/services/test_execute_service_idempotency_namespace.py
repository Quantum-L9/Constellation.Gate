"""Routing-level idempotency is namespaced by (tenant, action, key).

A flat key space does not merely lose a cache entry on collision -- it returns
another tenant's response packet.
"""

from __future__ import annotations

from typing import Any

import pytest
from constellation_node_sdk.transport.packet import TransportPacket, create_transport_packet

from constellation_gate.services.execute_service import ExecuteService


class EchoDispatcher:
    def __init__(self) -> None:
        self.calls = 0

    async def dispatch(
        self,
        packet: TransportPacket,
        *,
        deadline: Any = None,
    ) -> TransportPacket:
        self.calls += 1
        return packet.derive(
            packet_type="response",
            source_node="gate",
            destination_node=packet.address.reply_to,
            reply_to="gate",
            payload={"served_call": self.calls, **dict(packet.payload)},
        )


class NoWorkflows:
    def has_workflow(self, action: str) -> bool:
        return False

    async def execute(self, packet: TransportPacket, *, deadline: Any = None) -> TransportPacket:
        raise AssertionError("no workflow should run")


class PassthroughValidator:
    def validate(self, body: dict[str, Any]) -> TransportPacket:
        return TransportPacket.model_validate(body)


def _service(dispatcher: Any) -> ExecuteService:
    return ExecuteService(
        local_node="gate",
        ingress_validator=PassthroughValidator(),
        dispatcher=dispatcher,
        workflow_engine=NoWorkflows(),
        registry=None,
    )


def _body(*, action: str, tenant: str, key: str, marker: str) -> dict[str, Any]:
    return create_transport_packet(
        action=action,
        payload={"marker": marker},
        tenant=tenant,
        destination_node="gate",
        source_node="client",
        reply_to="client",
        idempotency_key=key,
        timeout_ms=30_000,
    ).model_dump_json_dict()


@pytest.mark.asyncio
async def test_same_tenant_action_key_is_served_from_cache() -> None:
    dispatcher = EchoDispatcher()
    service = _service(dispatcher)

    first = await service.execute(_body(action="score", tenant="acme", key="k", marker="1"))
    second = await service.execute(_body(action="score", tenant="acme", key="k", marker="2"))

    assert dispatcher.calls == 1, "the same logical operation must execute once"
    assert second.payload == first.payload


@pytest.mark.asyncio
async def test_different_tenants_never_share_a_cached_response() -> None:
    dispatcher = EchoDispatcher()
    service = _service(dispatcher)

    await service.execute(_body(action="score", tenant="tenant-a", key="k", marker="a"))
    result_b = await service.execute(_body(action="score", tenant="tenant-b", key="k", marker="b"))

    assert dispatcher.calls == 2, "tenant B must not be served tenant A's response"
    assert result_b.payload["marker"] == "b"


@pytest.mark.asyncio
async def test_different_actions_never_share_a_cached_response() -> None:
    dispatcher = EchoDispatcher()
    service = _service(dispatcher)

    await service.execute(_body(action="score", tenant="acme", key="k", marker="score"))
    result = await service.execute(_body(action="enrich", tenant="acme", key="k", marker="enrich"))

    assert dispatcher.calls == 2
    assert result.payload["marker"] == "enrich"


@pytest.mark.asyncio
async def test_unkeyed_requests_are_never_cached() -> None:
    dispatcher = EchoDispatcher()
    service = _service(dispatcher)

    body_1 = create_transport_packet(
        action="score",
        payload={"n": 1},
        tenant="acme",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    ).model_dump_json_dict()
    body_2 = create_transport_packet(
        action="score",
        payload={"n": 2},
        tenant="acme",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    ).model_dump_json_dict()

    await service.execute(body_1)
    await service.execute(body_2)

    assert dispatcher.calls == 2


@pytest.mark.asyncio
async def test_cached_replay_returns_the_original_canonical_response() -> None:
    """Decided contract: same logical operation -> same canonical response packet.

    The cached packet's lineage and causation describe the execution that
    actually happened. Re-deriving a fresh response for a replay would fabricate
    a hop chain and a generation bump for work that never ran, and would claim
    the replay packet as the parent of a result it did not produce. Callers
    correlate on header.correlation_id, which the original response carries.
    """
    dispatcher = EchoDispatcher()
    service = _service(dispatcher)

    first = await service.execute(_body(action="score", tenant="acme", key="k", marker="1"))
    replay = await service.execute(_body(action="score", tenant="acme", key="k", marker="2"))

    assert replay.header.packet_id == first.header.packet_id
    assert replay.header.correlation_id == first.header.correlation_id
    assert replay.header.causation_id == first.header.causation_id
    assert replay.lineage == first.lineage
