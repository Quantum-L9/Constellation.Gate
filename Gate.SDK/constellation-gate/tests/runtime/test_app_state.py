from __future__ import annotations

import pytest

from constellation_gate.runtime.app_state import AppState


def test_app_state_register_and_get() -> None:
    state = AppState()
    service = object()

    state.register("svc", service)
    assert state.get("svc") is service


def test_app_state_missing_raises() -> None:
    state = AppState()

    with pytest.raises(KeyError):
        state.get("missing")
