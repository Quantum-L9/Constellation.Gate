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


def _packet(timeout_ms: int):
    return create_transport_packet(
        action="converge",
        payload={"x": 1},
        tenant="t",
        destination_node="gate",
        source_node="client",
        reply_to="client",
        timeout_ms=timeout_ms,
    )


def test_response_margin_is_subtracted_from_advertised_budget() -> None:
    """Gate must answer before the caller's socket deadline (== advertised budget)."""
    policy = TimeoutPolicy(response_margin_ms=500)
    packet = _packet(30_000)
    assert policy.budget_ms(packet) == 29_500
    assert policy.resolve(packet) == 29.5


def test_response_margin_is_not_applied_to_a_budget_it_would_gut() -> None:
    policy = TimeoutPolicy(response_margin_ms=500)
    assert policy.budget_ms(_packet(1_000)) == 1_000
    assert policy.budget_ms(_packet(1_001)) == 501


def test_zero_margin_uses_the_whole_budget() -> None:
    assert TimeoutPolicy().budget_ms(_packet(30_000)) == 30_000


def test_negative_margin_is_rejected() -> None:
    import pytest

    with pytest.raises(ValueError, match="response_margin_ms"):
        TimeoutPolicy(response_margin_ms=-1)
