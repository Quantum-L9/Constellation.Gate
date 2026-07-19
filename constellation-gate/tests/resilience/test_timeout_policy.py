from __future__ import annotations

from constellation_node_sdk.transport.packet import create_transport_packet

from constellation_gate.resilience.timeout_policy import TimeoutPolicy


def test_timeout_policy_resolves_from_packet() -> None:
    packet = create_transport_packet(
        action="score",
        payload={"x": 1},
        tenant="t",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )
    policy = TimeoutPolicy(default_timeout_ms=10_000)
    timeout = policy.resolve(packet)
    assert timeout == packet.header.timeout_ms / 1000.0
