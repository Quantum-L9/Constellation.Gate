"""Gate routing-level idempotency (ADR-GATE-009, ADR-GATE-010).

A raw caller-supplied idempotency string is not a globally safe cache key. Two
unrelated tenants routinely mint the same key ("order-1", "retry-1"), and one
tenant may reuse a key across unrelated actions. Keying the routing cache on the
raw string alone lets one tenant's response be served to another -- a cross-tenant
data leak dressed up as a cache hit.

The routing-level cache identity is therefore ``(tenant org_id, canonical action,
idempotency key)``. Tenant identity is read from the canonical, integrity-hashed
``packet.tenant`` -- never from arbitrary payload fields, which Gate treats as
opaque and which a caller controls.

This store is PROCESS-LOCAL. It provides same-process duplicate response reuse.
It does NOT provide restart durability, cross-replica durability, failover
durability, or distributed exactly-once semantics, and it must never be described
as durable idempotency. Durable domain idempotency is owned by the worker/domain
authority (for canonical enrichment, the EIE persistence boundary).
"""

from __future__ import annotations

from typing import Any

from constellation_node_sdk.transport.packet import TransportPacket

# This store keeps entries for the lifetime of the process. It is deliberately
# NOT presented as durable infrastructure -- see the module docstring.
DURABLE: bool = False


def idempotency_namespace_key(packet: TransportPacket) -> str | None:
    """Build the namespaced routing cache key, or None when the packet has no key.

    Components are joined with a separator that cannot appear in the normalized
    tenant/action segments, so ``("a|b", "c")`` and ``("a", "b|c")`` cannot
    collide.
    """
    raw_key = packet.header.idempotency_key
    if not raw_key or not raw_key.strip():
        return None

    tenant = packet.tenant.org_id.strip().lower()
    action = packet.header.action.strip().lower()
    return "\x1f".join(("tenant:" + tenant, "action:" + action, "key:" + raw_key.strip()))


class IdempotencyStore:
    """Process-local response cache keyed by namespaced routing identity."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    def get(self, key: str) -> dict[str, Any] | None:
        return self._store.get(key)

    def set(self, key: str, value: dict[str, Any]) -> None:
        self._store[key] = value

    def exists(self, key: str) -> bool:
        return key in self._store

    def get_for_packet(self, packet: TransportPacket) -> dict[str, Any] | None:
        key = idempotency_namespace_key(packet)
        if key is None:
            return None
        return self._store.get(key)

    def set_for_packet(self, packet: TransportPacket, value: dict[str, Any]) -> bool:
        """Cache a result under the packet's namespaced key.

        Returns False (and caches nothing) when the packet carries no key.
        """
        key = idempotency_namespace_key(packet)
        if key is None:
            return False
        self._store[key] = value
        return True

    def __len__(self) -> int:
        return len(self._store)


def enforce_idempotency(packet: TransportPacket, store: IdempotencyStore) -> dict[str, Any] | None:
    """Return a cached response for this packet's namespaced identity, if any."""
    return store.get_for_packet(packet)
