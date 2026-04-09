from __future__ import annotations

from constellation_gate.runtime.health import health_status


def test_health_status_shape() -> None:
    result = health_status(
        service_name="constellation-gate",
        node_name="gate",
        environment="local",
    )

    assert result["status"] == "healthy"
    assert result["service_name"] == "constellation-gate"
    assert result["node_name"] == "gate"
    assert result["environment"] == "local"
