from __future__ import annotations

from typing import Dict, Optional


class IdempotencyStore:
    def __init__(self) -> None:
        self._store: Dict[str, dict] = {}

    def get(self, key: str) -> Optional[dict]:
        return self._store.get(key)

    def set(self, key: str, value: dict) -> None:
        self._store[key] = value

    def exists(self, key: str) -> bool:
        return key in self._store


def enforce_idempotency(packet, store: IdempotencyStore) -> Optional[dict]:
    key = packet.header.idempotency_key
    if not key:
        return None
    if store.exists(key):
        return store.get(key)
    return None
