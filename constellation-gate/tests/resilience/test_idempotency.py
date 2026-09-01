from __future__ import annotations

from typing import Any

import pytest
from constellation_node_sdk.transport.packet import create_transport_packet
from pydantic import ValidationError

from constellation_gate.resilience.idempotency import (
    IdempotencyStore,
    build_idempotency_scope,
    enforce_idempotency,
)


def _packet(
    *,
    action: str = "score",
    tenant: Any = "t",
    idempotency_key: str | None = "abc",
) -> Any:
    return create_transport_packet(
        action=action,
        payload={"x": 1},
        tenant=tenant,
        destination_node="gate",
        source_node="client",
        reply_to="client",
        idempotency_key=idempotency_key,
    )


def test_idempotency_returns_cached_response() -> None:
    store = IdempotencyStore()
    packet = _packet()

    scope = build_idempotency_scope(packet)
    assert scope is not None
    store.set(scope, {"status": "ok"})

    assert enforce_idempotency(packet, store) == {"status": "ok"}


def test_unkeyed_packet_has_no_scope_and_never_hits_cache() -> None:
    store = IdempotencyStore()
    packet = _packet(idempotency_key=None)

    assert build_idempotency_scope(packet) is None
    assert enforce_idempotency(packet, store) is None


def test_blank_idempotency_key_cannot_reach_gate() -> None:
    # A whitespace-only key would namespace to a scope indistinguishable from
    # the unkeyed case. The canonical packet model rejects it before ingress,
    # so Gate never has to disambiguate "blank key" from "no key".
    with pytest.raises(ValidationError):
        _packet(idempotency_key="   ")


def test_same_key_different_tenants_are_separate_scopes() -> None:
    store = IdempotencyStore()
    tenant_a = _packet(tenant="tenant-a")
    tenant_b = _packet(tenant="tenant-b")

    scope_a = build_idempotency_scope(tenant_a)
    assert scope_a is not None
    store.set(scope_a, {"owner": "tenant-a"})

    assert enforce_idempotency(tenant_a, store) == {"owner": "tenant-a"}
    # Tenant B must NOT read tenant A's response packet.
    assert enforce_idempotency(tenant_b, store) is None
    assert build_idempotency_scope(tenant_b) != scope_a


def test_same_key_different_actions_are_separate_scopes() -> None:
    store = IdempotencyStore()
    score = _packet(action="score")
    enrich = _packet(action="enrich")

    scope_score = build_idempotency_scope(score)
    assert scope_score is not None
    store.set(scope_score, {"action": "score"})

    assert enforce_idempotency(score, store) == {"action": "score"}
    assert enforce_idempotency(enrich, store) is None


def test_same_tenant_action_and_key_is_the_same_operation() -> None:
    store = IdempotencyStore()
    first = _packet()
    second = _packet()

    # Distinct packets (distinct packet_id) for the same logical operation.
    assert first.header.packet_id != second.header.packet_id

    scope = build_idempotency_scope(first)
    assert scope is not None
    store.set(scope, {"status": "ok"})

    assert enforce_idempotency(second, store) == {"status": "ok"}


def test_scope_is_case_insensitive_on_tenant_and_action() -> None:
    lower = _packet(action="score", tenant="acme")
    upper = _packet(action="SCORE", tenant="ACME")
    assert build_idempotency_scope(lower) == build_idempotency_scope(upper)
