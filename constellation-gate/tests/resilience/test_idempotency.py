from __future__ import annotations

from constellation_node_sdk.transport.packet import create_transport_packet

from constellation_gate.resilience.idempotency import (
    IdempotencyStore,
    enforce_idempotency,
    idempotency_namespace_key,
)


def _packet(*, tenant: str, action: str, key: str | None):
    return create_transport_packet(
        action=action,
        payload={"x": 1},
        tenant=tenant,
        destination_node="gate",
        source_node="client",
        reply_to="client",
        idempotency_key=key,
    )


def test_idempotency_returns_cached_response_for_same_logical_operation() -> None:
    store = IdempotencyStore()
    packet = _packet(tenant="t", action="score", key="abc")

    assert store.set_for_packet(packet, {"status": "ok"}) is True

    assert enforce_idempotency(packet, store) == {"status": "ok"}


def test_idempotency_is_namespaced_by_tenant() -> None:
    """Same raw key in two tenants must never collide (ADR-GATE-009)."""
    store = IdempotencyStore()
    tenant_a = _packet(tenant="tenant-a", action="score", key="shared-key")
    tenant_b = _packet(tenant="tenant-b", action="score", key="shared-key")

    store.set_for_packet(tenant_a, {"owner": "tenant-a"})

    assert enforce_idempotency(tenant_a, store) == {"owner": "tenant-a"}
    assert enforce_idempotency(tenant_b, store) is None


def test_idempotency_is_namespaced_by_action() -> None:
    """Same tenant reusing a key across unrelated actions must not collide."""
    store = IdempotencyStore()
    score = _packet(tenant="t", action="score", key="shared-key")
    converge = _packet(tenant="t", action="converge", key="shared-key")

    store.set_for_packet(score, {"from": "score"})

    assert enforce_idempotency(score, store) == {"from": "score"}
    assert enforce_idempotency(converge, store) is None


def test_idempotency_ignores_packets_without_a_key() -> None:
    store = IdempotencyStore()
    packet = _packet(tenant="t", action="score", key=None)

    assert idempotency_namespace_key(packet) is None
    assert store.set_for_packet(packet, {"status": "ok"}) is False
    assert enforce_idempotency(packet, store) is None
    assert len(store) == 0


def test_raw_key_alone_is_not_a_cache_hit() -> None:
    """A raw, unnamespaced key must not resolve -- that was the unsafe identity."""
    store = IdempotencyStore()
    packet = _packet(tenant="t", action="score", key="abc")

    store.set("abc", {"status": "leaked"})

    assert enforce_idempotency(packet, store) is None


def test_namespace_key_components_cannot_be_confused() -> None:
    """Boundary-shifting between components must produce different keys."""
    store = IdempotencyStore()
    left = _packet(tenant="a", action="b.c", key="d")
    right = _packet(tenant="a", action="b", key="c.d")

    assert idempotency_namespace_key(left) != idempotency_namespace_key(right)

    store.set_for_packet(left, {"which": "left"})
    assert enforce_idempotency(right, store) is None
