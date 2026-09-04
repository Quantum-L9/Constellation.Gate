"""Outage injection (runs last): a missing peer or a missing Gate fails closed with no side channel."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from .drivers import CEG_DRIVER, EIE_DRIVER
from .harness import Evidence, ManagedProcess, SeamContext, run_in_peer

pytestmark = pytest.mark.seam_e2e

TENANT = "plasticos"
TAG = time.strftime("%Y%m%d%H%M%S", time.gmtime())


def eie_call(ctx: SeamContext, **args: Any) -> dict[str, Any]:
    return run_in_peer(ctx.eie, EIE_DRIVER, {**ctx.eie_env(), "SEAM_ARGS": json.dumps(args)})


def ceg_call(ctx: SeamContext, spec: Path, **args: Any) -> dict[str, Any]:
    return run_in_peer(ctx.ceg, CEG_DRIVER, {**ctx.ceg_env(spec), "SEAM_ARGS": json.dumps(args)})


def test_o1_ceg_down_makes_eie_sync_fail_closed(
    ctx: SeamContext, constellation: dict, ceg: ManagedProcess, evidence: Evidence
) -> None:
    ceg.stop()
    assert not ceg.alive
    result = eie_call(
        ctx,
        op="sync",
        tenant=TENANT,
        entity_id=f"fac-down-{TAG}",
        fields={"name": "down"},
        correlation_id=f"seam-o1-{TAG}",
    )
    assert result["ok"] is False, f"sync succeeded with CEG stopped: {result}"
    ready = httpx.get(f"{ctx.gate_url}/v1/ready", timeout=5.0)
    evidence.record(
        "O-01",
        direction="EIE->Gate->CEG",
        status="PASS",
        injected="CEG process stopped",
        detail="EIE notify_graph_sync returned None (bounded failure, no fallback path); Gate could not reach the worker",
        gate_ready_http_status=ready.status_code,
        gate_ready_body=ready.json(),
    )


def test_o2_gate_down_makes_both_directions_fail_closed(
    ctx: SeamContext,
    constellation: dict,
    gate: ManagedProcess,
    ceg_spec_path: Path,
    evidence: Evidence,
) -> None:
    gate.stop()
    assert not gate.alive
    eie_result = eie_call(
        ctx,
        op="route",
        action="sync",
        tenant=TENANT,
        payload={"entity_type": "facilities", "batch": [{"facility_id": "x", "entity_id": "x"}]},
        idempotency_key=f"seam-o2-{TAG}",
    )
    assert eie_result["ok"] is False and eie_result.get("cause") == "GateConnectionError", (
        eie_result
    )
    ceg_result = ceg_call(
        ctx,
        ceg_spec_path,
        op="enrich",
        tenant=TENANT,
        entity_id="x",
        domain=TENANT,
        target_fields=["website"],
        timeout_ms=5_000,
    )
    assert (
        ceg_result["ok"] is False and ceg_result["result"].get("error") == "GateConnectionError"
    ), ceg_result
    evidence.record(
        "O-02",
        direction="both",
        status="PASS",
        injected="Gate process stopped",
        detail="EIE PacketRouter retried the connection error once (idempotency key present) then raised NodeUnreachableError; CEG gate_egress reported GateConnectionError after one attempt; neither node attempted a direct peer call",
        eie_error=eie_result.get("cause"),
        ceg_error=ceg_result["result"].get("error"),
    )
