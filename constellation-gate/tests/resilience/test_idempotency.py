from __future__ import annotations

from constellation_gate.resilience.idempotency import IdempotencyStore, enforce_idempotency
from constellation_node_sdk.transport.packet import create_transport_packet


def test_idempotency_returns_cached_response() -> None:
    store = IdempotencyStore()
    packet = create_transport_packet(
        action="score",
        payload={"x": 1},
        tenant="t",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    ).derive(idempotency_key="abc")

    store.set("abc", {"status": "ok"})
    result = enforce_idempotency(packet, store)
    assert result == {"status": "ok"}
