"""Failure injection against the live constellation: every rejection must be Gate's or the SDK's, never a fallback."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from .drivers import CEG_DRIVER, EIE_DRIVER
from .harness import Evidence, ManagedProcess, SeamContext, count_matching, run_in_peer

pytestmark = pytest.mark.seam_e2e

TENANT = "plasticos"
TAG = time.strftime("%Y%m%d%H%M%S", time.gmtime())
SYNC_PAYLOAD = {
    "entity_type": "facilities",
    "batch": [
        {
            "facility_id": f"fac-fi-{TAG}",
            "entity_id": f"fac-fi-{TAG}",
            "name": "FI",
            "polymer_type": "PET",
        }
    ],
}


def eie_call(ctx: SeamContext, **args: Any) -> dict[str, Any]:
    return run_in_peer(ctx.eie, EIE_DRIVER, {**ctx.eie_env(), "SEAM_ARGS": json.dumps(args)})


def ceg_call(ctx: SeamContext, spec: Path, **args: Any) -> dict[str, Any]:
    return run_in_peer(ctx.ceg, CEG_DRIVER, {**ctx.ceg_env(spec), "SEAM_ARGS": json.dumps(args)})


def test_f1_malformed_body_is_rejected_by_gate(
    ctx: SeamContext, constellation: dict, evidence: Evidence
) -> None:
    result = eie_call(
        ctx, op="post_malformed", url=f"{ctx.gate_url}/v1/execute", body='{"header": "not a packet"'
    )
    assert 400 <= result["status_code"] < 500, result
    evidence.record(
        "F-01",
        direction="EIE->Gate",
        status="PASS",
        injected="malformed JSON body",
        http_status=result["status_code"],
        body=result["body"][:200],
    )


def test_f2_unsigned_packet_is_rejected_by_gate(
    ctx: SeamContext, constellation: dict, evidence: Evidence
) -> None:
    result = eie_call(
        ctx,
        op="post_unsigned",
        url=f"{ctx.gate_url}/v1/execute",
        action="sync",
        tenant=TENANT,
        payload=SYNC_PAYLOAD,
    )
    assert result["status_code"] in {400, 401, 403}, f"Gate accepted an unsigned packet: {result}"
    evidence.record(
        "F-02",
        direction="EIE->Gate",
        status="PASS",
        injected="structurally valid, unsigned TransportPacket",
        http_status=result["status_code"],
        body=result["body"][:200],
    )


def test_f3_unknown_action_fails_closed_without_retry(
    ctx: SeamContext, constellation: dict, evidence: Evidence
) -> None:
    result = eie_call(
        ctx,
        op="route",
        action="graph-query",
        tenant=TENANT,
        payload={"q": 1},
        idempotency_key=f"seam-unknown-{TAG}",
    )
    assert result["ok"] is False, result
    assert result["status_code"] == 404 or "404" in str(result.get("cause_detail")), result
    evidence.record(
        "F-03",
        direction="EIE->Gate",
        status="PASS",
        injected="action `graph-query` (no owner in Gate)",
        detail="Gate answered 404 route-unavailable; EIE PacketRouter raised NodeUnreachableError without retrying a 4xx",
        error=result.get("cause"),
        status_code=result.get("status_code"),
    )


def test_f4a_direct_eie_to_ceg_call_is_refused_by_ceg_ingress(
    ctx: SeamContext, constellation: dict, evidence: Evidence
) -> None:
    result = eie_call(
        ctx,
        op="post_direct",
        url=f"{ctx.ceg.url}/v1/execute",
        destination_node="graph",
        action="sync",
        tenant=TENANT,
        payload=SYNC_PAYLOAD,
    )
    assert result["status_code"] in {400, 401, 403}, (
        f"CEG accepted a packet that did not come from Gate: {result}"
    )
    evidence.record(
        "F-04a",
        direction="EIE->CEG (direct, bypassing Gate)",
        status="PASS",
        injected="node-authored packet posted straight to CEG /v1/execute",
        http_status=result["status_code"],
        body=result["body"][:200],
    )


def test_f4b_direct_ceg_to_eie_call_is_refused_by_eie_ingress(
    ctx: SeamContext,
    constellation: dict,
    eie: ManagedProcess,
    ceg_spec_path: Path,
    evidence: Evidence,
) -> None:
    """A node-authored packet posted straight to EIE must not reach a handler.

    EIE's ingress is the SDK worker runtime. With L9_RETURN_TRANSPORT_ERRORS
    (SDK default) it answers a *signed failure packet* over HTTP 200 rather than
    an HTTP 4xx. The payload is a valid EnrichRequest on purpose: had the handler
    run, EIE would have answered an EnrichResponse (a `state` field and a
    `pipeline_started` log line). Neither may appear.
    """
    handler_runs_before = count_matching(eie.log_text(), "pipeline_started")
    result = ceg_call(
        ctx,
        ceg_spec_path,
        op="post_direct",
        url=f"{ctx.eie.url}/v1/execute",
        destination_node="enrichment-engine",
        action="enrich",
        tenant=TENANT,
        payload={
            "entity": {"entity_id": f"direct-{TAG}", "name": "Direct call"},
            "object_type": TENANT,
            "objective": "must never be executed: this packet bypassed Gate",
            "schema": {"website": "string"},
        },
    )
    status = result["status_code"]
    body = result.get("body_json") or {}
    refused_by_http = status in {400, 401, 403}
    refused_by_packet = (
        status == 200
        and isinstance(body, dict)
        and body.get("header", {}).get("packet_type") == "failure"
    )
    assert refused_by_http or refused_by_packet, (
        f"EIE accepted a packet that did not come from Gate: {result}"
    )
    payload = body.get("payload", {}) if isinstance(body, dict) else {}
    if refused_by_packet:
        assert "state" not in payload, f"EIE's enrich handler ran on a direct packet: {payload}"
        assert body["address"]["source_node"] == "enrichment-engine", body["address"]
        assert body["security"].get("signature"), "failure packet is unsigned"
    time.sleep(0.3)
    assert count_matching(eie.log_text(), "pipeline_started") == handler_runs_before, (
        "EIE's enrichment pipeline started for a packet that bypassed Gate"
    )
    evidence.record(
        "F-04b",
        direction="CEG->EIE (direct, bypassing Gate)",
        status="PASS",
        injected="node-authored, valid EnrichRequest posted straight to EIE /v1/execute",
        http_status=status,
        refusal="http"
        if refused_by_http
        else "signed failure packet (HTTP 200, L9_RETURN_TRANSPORT_ERRORS)",
        error_payload=payload,
        handler_executed=False,
        findings=[
            (
                "SEAM-INGRESS-01: CEG's gate-only middleware answers HTTP 403 while EIE's SDK runtime answers a "
                + "signed failure packet over HTTP 200; both refuse before any handler runs"
            ),
            (
                "SDK-OBS-01: the SDK runtime reports a gate-only ingress rejection as a redacted 'ValueError' failure "
                + "packet and writes no log line, so it is indistinguishable from a handler ValueError without a log"
            ),
        ],
    )


def test_f5_expired_deadline_never_reaches_a_worker_as_success(
    ctx: SeamContext, constellation: dict, evidence: Evidence
) -> None:
    result = eie_call(
        ctx,
        op="exec_raw",
        action="sync",
        tenant=TENANT,
        payload=SYNC_PAYLOAD,
        idempotency_key=f"seam-deadline-{TAG}",
        timeout_ms=1,
        timeout_seconds=5.0,
    )
    assert result["ok"] is False, f"a 1 ms budget produced a success: {result}"
    evidence.record(
        "F-05",
        direction="EIE->Gate->CEG",
        status="PASS",
        injected="timeout_ms=1 on `sync`",
        detail="one deadline derived from header.timeout_ms; the operation failed closed as observed",
        error=result.get("error"),
        status_code=result.get("status_code"),
        error_detail=str(result.get("detail"))[:200],
    )


def test_f6_duplicate_idempotency_key_returns_the_cached_result(
    ctx: SeamContext, constellation: dict, evidence: Evidence
) -> None:
    key = f"seam-dup-{TAG}"
    batch = [
        {
            "facility_id": f"fac-dup-{TAG}",
            "entity_id": f"fac-dup-{TAG}",
            "name": "Dup",
            "polymer_type": "LDPE",
        }
    ]
    first = eie_call(
        ctx,
        op="gsc_sync",
        entity_type="facilities",
        batch=batch,
        tenant=TENANT,
        idempotency_key=key,
    )
    second = eie_call(
        ctx,
        op="gsc_sync",
        entity_type="facilities",
        batch=batch,
        tenant=TENANT,
        idempotency_key=key,
    )
    assert first["ok"] and second["ok"], (first, second)
    assert first["result"]["packet_id"] == second["result"]["packet_id"], (
        "Gate executed the same logical operation twice"
    )
    evidence.record(
        "F-06",
        direction="EIE->Gate->CEG",
        status="PASS",
        injected="same idempotency key twice",
        detail="second call returned the cached response packet (same packet_id)",
        packet_id=first["result"]["packet_id"],
    )


def test_f7_replayed_packet_is_not_executed_twice(
    ctx: SeamContext, constellation: dict, ceg_spec_path: Path, evidence: Evidence
) -> None:
    entity = f"fac-replay-{TAG}"
    payload = {
        "entity_type": "facilities",
        "batch": [
            {"facility_id": entity, "entity_id": entity, "name": "Replay", "polymer_type": "PS"}
        ],
    }
    result = eie_call(
        ctx,
        op="replay",
        action="sync",
        tenant=TENANT,
        payload=payload,
        idempotency_key=f"seam-replay-{TAG}",
    )
    attempts = result["attempts"]
    assert attempts[0]["ok"], attempts
    rows = ceg_call(
        ctx,
        ceg_spec_path,
        op="cypher",
        cypher="MATCH (n {facility_id: $id}) RETURN count(n) AS c",
        parameters={"id": entity},
    )
    assert rows["rows"][0]["c"] == 1, (
        f"replayed packet was merged more than once or not at all: {rows}"
    )
    if attempts[1]["ok"]:
        assert attempts[1]["packet_id"] == attempts[0]["packet_id"], (
            "second delivery was executed as a new operation"
        )
    evidence.record(
        "F-07",
        direction="EIE->Gate->CEG",
        status="PASS",
        injected="identical signed packet delivered twice",
        attempts=attempts,
        graph_rows=rows["rows"],
    )
