from __future__ import annotations

from typing import Any

from constellation_node_sdk.transport.packet import TransportPacket


class IdempotencyStore:
    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    def get(self, key: str) -> dict[str, Any] | None:
        return self._store.get(key)

    def set(self, key: str, value: dict[str, Any]) -> None:
        self._store[key] = value

    def exists(self, key: str) -> bool:
        return key in self._store


def enforce_idempotency(
    packet: TransportPacket, store: IdempotencyStore
) -> dict[str, Any] | None:
    key = packet.header.idempotency_key
    if not key:
        return None
    if store.exists(key):
        return store.get(key)
    return None
