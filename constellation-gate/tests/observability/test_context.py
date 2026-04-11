from __future__ import annotations

from constellation_gate.observability.context import clear_context, get_context, set_context


def test_context_set_and_get() -> None:
    clear_context()
    set_context(packet_id="p1", action="score")
    context = get_context()

    assert context["packet_id"] == "p1"
    assert context["action"] == "score"


def test_context_clear_resets_state() -> None:
    set_context(packet_id="p2")
    clear_context()

    assert get_context() == {}
