"""Startup wiring: static registry load, health re-probe loop, request context.

`create_app()` used to start an HTTP client pool and nothing else. The
shipped registry YAML was never read, the health monitor was never started,
and the JSON log formatter was never installed.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from constellation_gate.api import dependencies as deps
from constellation_gate.api.main import create_app
from constellation_gate.config.settings import GateSettings

SHIPPED = Path(__file__).resolve().parents[2] / "src/constellation_gate/config/node_registry.yaml"


@pytest.fixture
def isolated_deps(monkeypatch: pytest.MonkeyPatch):
    deps.get_registry.cache_clear()
    deps.get_execute_service.cache_clear()
    deps.get_ingress_validator.cache_clear()
    deps.get_dispatcher.cache_clear()
    deps.get_workflow_engine.cache_clear()

    def _install(settings: GateSettings) -> None:
        monkeypatch.setattr(deps, "get_gate_settings", lambda: settings)

    yield _install

    deps.get_registry.cache_clear()
    deps.get_execute_service.cache_clear()
    deps.get_ingress_validator.cache_clear()
    deps.get_dispatcher.cache_clear()
    deps.get_workflow_engine.cache_clear()


def test_lifespan_loads_static_registry_and_starts_health_monitor(isolated_deps) -> None:
    isolated_deps(
        GateSettings(
            environment="local",
            local_node="gate",
            node_registry_path=str(SHIPPED),
            health_probe_interval_seconds=3600.0,
        )
    )
    app = create_app()
    with TestClient(app) as client:
        assert "enrichment-engine" in deps.get_registry().snapshot()
        monitor = app.state.runtime.get("health_monitor")
        assert monitor.running is True
        assert monitor.interval_seconds == 3600.0
        response = client.get("/v1/health")
        assert response.status_code == 200
    assert monitor.running is False


def test_zero_probe_interval_disables_the_monitor(isolated_deps) -> None:
    isolated_deps(
        GateSettings(environment="local", local_node="gate", health_probe_interval_seconds=0.0)
    )
    app = create_app()
    with TestClient(app):
        with pytest.raises(KeyError):
            app.state.runtime.get("health_monitor")


def test_execute_service_receives_resilience_settings(isolated_deps) -> None:
    isolated_deps(
        GateSettings(
            environment="local",
            local_node="gate",
            idempotency_ttl_seconds=120.0,
            response_margin_ms=750,
        )
    )
    service = deps.get_execute_service()
    assert service.timeout_policy.response_margin_ms == 750
    assert service.idempotency_store._ttl == 120.0


def test_request_id_is_echoed_and_honoured(isolated_deps) -> None:
    isolated_deps(GateSettings(environment="local", local_node="gate"))
    app = create_app()
    with TestClient(app) as client:
        generated = client.get("/v1/health").headers["X-Request-ID"]
        assert generated
        echoed = client.get("/v1/health", headers={"X-Request-ID": "odoo-run-42"})
        assert echoed.headers["X-Request-ID"] == "odoo-run-42"


def test_lifespan_does_not_replace_an_existing_root_handler(isolated_deps) -> None:
    isolated_deps(GateSettings(environment="local", local_node="gate"))
    root = logging.getLogger()
    sentinel = logging.NullHandler()
    root.addHandler(sentinel)
    try:
        with TestClient(create_app()):
            assert sentinel in root.handlers
    finally:
        root.removeHandler(sentinel)
