from __future__ import annotations

from constellation_gate.runtime.lifecycle import LifecycleManager


def test_lifecycle_start_stop() -> None:
    manager = LifecycleManager()

    manager.start()
    assert manager.started is True

    manager.stop()
    assert manager.stopped is True
