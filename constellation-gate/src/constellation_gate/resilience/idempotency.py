"""Routing-level idempotency, namespaced by canonical routing identity.

A bare ``header.idempotency_key`` is a caller-chosen string. Two tenants that
independently pick ``"req-1"``, or one tenant reusing a key across two different
actions, would collide in a flat key space -- and a collision here does not
merely lose a cache entry, it returns *another tenant's response packet*.

The namespace is therefore (tenant org_id, normalized action, key). Tenant
identity is read from the canonical SDK ``TransportPacket.tenant`` context,
never from the opaque domain payload: the payload is not Gate's to interpret,
and a payload-derived tenant would be attacker-controlled.

This store is process-local. It is a routing-level cache, not durable
distributed idempotency infrastructure, and must not be represented as one.
"""

from __future__ import annotations

from typing import Any

from constellation_node_sdk.transport.packet import TransportPacket

_NAMESPACE_SEPARATOR = "\x1f"  # ASCII unit separator: cannot appear in these fields


def build_idempotency_scope(packet: TransportPacket) -> str | None:
    """Return the namespaced idempotency scope, or ``None`` when unkeyed.

    Namespace: ``tenant.org_id`` + normalized ``header.action`` + the caller's
    ``header.idempotency_key``.
    """
    key = packet.header.idempotency_key
    if key is None:
        return None
    normalized_key = str(key).strip()
    if not normalized_key:
        return None

    tenant = packet.tenant.org_id.strip().lower()
    action = packet.header.action.strip().lower()
    return _NAMESPACE_SEPARATOR.join((tenant, action, normalized_key))


class IdempotencyStore:
    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    def get(self, key: str) -> dict[str, Any] | None:
        return self._store.get(key)

    def set(self, key: str, value: dict[str, Any]) -> None:
        self._store[key] = value

    def exists(self, key: str) -> bool:
        return key in self._store

    def size(self) -> int:
        return len(self._store)


def enforce_idempotency(packet: TransportPacket, store: IdempotencyStore) -> dict[str, Any] | None:
    """Look up a previously completed operation for this packet's scope."""
    scope = build_idempotency_scope(packet)
    if scope is None:
        return None
    if store.exists(scope):
        return store.get(scope)
    return None
