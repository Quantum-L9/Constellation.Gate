"""Bidirectional real-process E2E: EIE -> Gate -> CEG and CEG -> Gate -> EIE.

Every call below leaves one process, crosses a real socket into the real Gate,
is routed by Gate's live registry to the real peer process, and comes back.
No handler is invoked directly and nothing is mocked.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from .drivers import CEG_DRIVER, EIE_DRIVER
from .harness import Evidence, ManagedProcess, SeamContext, count_matching, run_in_peer

pytestmark = pytest.mark.seam_e2e

TENANT = "plasticos"
SESSION_TAG = time.strftime("%Y%m%d%H%M%S", time.gmtime())
ENTITY_ID = f"fac-e2e-{SESSION_TAG}"
FIELDS = {
    "name": "Seam E2E Facility",
    "polymer_type": "HDPE",
    "city": "Austin",
    "capacity_tons": 120.5,
}


def eie_call(ctx: SeamContext, **args: Any) -> dict[str, Any]:
    return run_in_peer(ctx.eie, EIE_DRIVER, {**ctx.eie_env(), "SEAM_ARGS": json.dumps(args)})


def ceg_call(ctx: SeamContext, spec: Path, **args: Any) -> dict[str, Any]:
    return run_in_peer(ctx.ceg, CEG_DRIVER, {**ctx.ceg_env(spec), "SEAM_ARGS": json.dumps(args)})


def execute_hits(proc: ManagedProcess) -> int:
    return count_matching(proc.log_text(), "/v1/execute")


def test_gate_registry_holds_both_seam_nodes(
    ctx: SeamContext, constellation: dict, evidence: Evidence
) -> None:
    assert "enrichment-engine" in constellation, (
        f"EIE did not register with Gate: {list(constellation)}"
    )
    assert "graph" in constellation, f"CEG did not register with Gate: {list(constellation)}"
    rendered = json.dumps(constellation)
    assert ctx.eie.url in rendered, "Gate does not know EIE's real address"
    assert ctx.ceg.url in rendered, "Gate does not know CEG's real address"
    for action in (
        "converge",
        "enrich",
        "enrich-and-sync",
        "graph-inference-result",
        "match",
        "sync",
        "outcomes",
        "resolve",
    ):
        assert f'"{action}"' in rendered, f"action {action!r} not advertised to Gate by any node"
    evidence.record(
        "REG-01",
        direction="control-plane",
        status="PASS",
        detail="both nodes self-registered with Gate over HTTP (SDK register_node) and Gate's live registry holds their real addresses",
        nodes=sorted(constellation),
    )


def test_gate_routing_readiness_requires_whole_seam(
    ctx: SeamContext, constellation: dict, evidence: Evidence
) -> None:
    response = httpx.get(f"{ctx.gate_url}/v1/ready", timeout=5.0)
    body = response.json()
    assert response.status_code == 200, body
    assert body.get("ready") is True, body
    evidence.record(
        "REG-02",
        direction="control-plane",
        status="PASS",
        detail="/v1/ready is 200 with every seam action routable",
        ready=body,
    )


def test_a1_eie_sync_is_routed_by_gate_and_persisted_by_ceg(
    ctx: SeamContext,
    constellation: dict,
    gate: ManagedProcess,
    ceg: ManagedProcess,
    ceg_spec_path: Path,
    evidence: Evidence,
) -> None:
    gate_before, ceg_before = execute_hits(gate), execute_hits(ceg)
    result = eie_call(
        ctx,
        op="sync",
        tenant=TENANT,
        entity_id=ENTITY_ID,
        fields=FIELDS,
        correlation_id=f"seam-a1-{SESSION_TAG}",
    )
    assert result["ok"], f"EIE PacketRouter.notify_graph_sync failed: {result}"
    payload = result["result"]
    assert payload.get("status") == "success", f"CEG sync did not succeed: {payload}"
    assert payload.get("packet_id"), payload
    time.sleep(0.5)
    assert execute_hits(gate) > gate_before, "Gate access log shows no new /v1/execute for the sync"
    assert execute_hits(ceg) > ceg_before, (
        "CEG access log shows no new /v1/execute: Gate did not dispatch to the real CEG process"
    )

    rows = ceg_call(
        ctx,
        ceg_spec_path,
        op="cypher",
        cypher="MATCH (n {facility_id: $id}) RETURN labels(n) AS labels, n.facility_id AS facility_id, n.polymer_type AS polymer_type, n.enriched_by AS enriched_by",
        parameters={"id": ENTITY_ID},
    )
    assert rows["ok"] and rows["rows"], f"entity {ENTITY_ID} was not written to CEG's graph: {rows}"
    row = rows["rows"][0]
    assert row["polymer_type"] == "HDPE"
    evidence.record(
        "A-01",
        direction="EIE->Gate->CEG",
        status="PASS",
        action="sync",
        detail="EIE PacketRouter (production path) sent `sync`; Gate dispatched to CEG; CEG merged the row into Neo4j",
        response=payload,
        graph_row=row,
        gate_execute_delta=execute_hits(gate) - gate_before,
        ceg_execute_delta=execute_hits(ceg) - ceg_before,
    )


def test_a2_eie_match_is_routed_by_gate(
    ctx: SeamContext, constellation: dict, ceg: ManagedProcess, evidence: Evidence
) -> None:
    ceg_before = execute_hits(ceg)
    result = eie_call(
        ctx,
        op="gsc_match",
        tenant=TENANT,
        query={"polymer_type": "HDPE", "volume_tons": 10.0, "requires_active_supply": False},
        match_direction="supply_opportunity_to_buyer_facility",
        top_n=5,
    )
    payload = result["result"]
    assert result["ok"], f"CEG match failed through Gate: {payload}"
    assert payload.get("packet_id"), payload
    time.sleep(0.3)
    assert execute_hits(ceg) > ceg_before
    evidence.record(
        "A-02",
        direction="EIE->Gate->CEG",
        status="PASS",
        action="match",
        detail="EIE GraphSyncClient.match (production path) routed by Gate to CEG; CEG answered with a match result set",
        response_keys=sorted(payload),
        match_count=len(payload.get("matches", payload.get("results", []) or [])),
    )


def test_a3_eie_outcomes_is_routed_by_gate(
    ctx: SeamContext, constellation: dict, ceg: ManagedProcess, evidence: Evidence
) -> None:
    ceg_before = execute_hits(ceg)
    result = eie_call(
        ctx,
        op="gsc_outcome",
        tenant=TENANT,
        outcome={
            "match_id": f"match-e2e-{SESSION_TAG}",
            "candidate_id": ENTITY_ID,
            "outcome": "success",
        },
        idempotency_key=f"seam-outcome-{SESSION_TAG}",
    )
    payload = result["result"]
    assert result["ok"], f"CEG outcomes failed through Gate: {payload}"
    time.sleep(0.3)
    assert execute_hits(ceg) > ceg_before
    evidence.record(
        "A-03",
        direction="EIE->Gate->CEG",
        status="PASS",
        action="outcomes",
        detail="EIE GraphSyncClient.send_outcome (production path, CEG action name `outcomes`) routed by Gate to CEG",
        response=payload,
    )


def test_a4_response_packet_lineage_proves_gate_authored_dispatch(
    ctx: SeamContext, constellation: dict, evidence: Evidence
) -> None:
    """What the originator gets back is the worker's response to Gate's derived packet.

    Gate relays the worker's response packet to the originator unchanged (no
    re-addressing, no Gate hop on the return leg). The evidence that Gate sat in
    the middle is therefore carried by the packet Gate authored: provenance
    (origin_kind=gate, resolved_by_gate=true, route_kind=external_ingress), the
    preserved correlation id, the worker's response hop, and the signature.
    """
    entity = f"{ENTITY_ID}-hops"
    correlation_id = f"seam-a4-{SESSION_TAG}"
    result = eie_call(
        ctx,
        op="exec_raw",
        action="sync",
        tenant=TENANT,
        payload={
            "entity_type": "facilities",
            "batch": [
                {
                    "facility_id": entity,
                    "entity_id": entity,
                    "name": "Hop trace facility",
                    "polymer_type": "PP",
                }
            ],
        },
        idempotency_key=f"seam-hops-{SESSION_TAG}",
        timeout_ms=10_000,
        correlation_id=correlation_id,
    )
    assert result["ok"], result
    packet = result["packet"]
    hops = [
        (h.get("node"), h.get("direction"), h.get("status")) for h in packet.get("hop_trace", [])
    ]
    assert ("graph", "response", "completed") in hops, f"no CEG response hop in the lineage: {hops}"
    provenance = packet["provenance"]
    assert provenance["origin_kind"] == "gate", provenance
    assert provenance["resolved_by_gate"] is True, provenance
    assert provenance.get("route_kind") == "external_ingress", provenance
    assert provenance.get("original_source_node") == "enrichment-engine", provenance
    assert packet["header"]["correlation_id"] == correlation_id
    assert packet["header"]["packet_type"] == "response"
    assert packet["security"].get("signature"), "response packet is unsigned"
    assert packet["security"].get("signing_key_id") == ctx.key_ids["ceg"], packet["security"]
    evidence.record(
        "A-04",
        direction="EIE->Gate->CEG",
        status="PASS",
        action="sync",
        detail=(
            "response lineage: Gate-authored provenance (origin_kind=gate, resolved_by_gate, "
            "route_kind=external_ingress, original_source_node=enrichment-engine), correlation id preserved, "
            "CEG response hop present, response signed with CEG's key id"
        ),
        hop_trace=hops,
        address=packet["address"],
        provenance=provenance,
        packet_id=packet["header"]["packet_id"],
        correlation_id=packet["header"].get("correlation_id"),
        finding=(
            "GATE-RETURN-01: Gate relays the worker response packet to the originator unchanged; "
            "the address block is worker->gate and no Gate hop is appended on the return leg"
        ),
    )


def test_b1_ceg_enrichment_request_is_routed_by_gate_to_eie(
    ctx: SeamContext,
    constellation: dict,
    gate: ManagedProcess,
    eie: ManagedProcess,
    ceg_spec_path: Path,
    evidence: Evidence,
) -> None:
    gate_before, eie_before = execute_hits(gate), execute_hits(eie)
    result = ceg_call(
        ctx,
        ceg_spec_path,
        op="enrich",
        tenant=TENANT,
        entity_id=ENTITY_ID,
        domain=TENANT,
        target_fields=["website", "polymer_type"],
        entity={"name": "Seam E2E Facility"},
        timeout_ms=20_000,
        correlation_id=f"seam-b1-{SESSION_TAG}",
    )
    dispatch = result["result"]
    assert dispatch.get("packet_id"), f"no packet came back from Gate: {dispatch}"
    assert dispatch.get("packet_type") in {"response", "failure"}, dispatch
    time.sleep(0.5)
    assert execute_hits(gate) > gate_before, "Gate saw no /v1/execute from CEG"
    assert execute_hits(eie) > eie_before, (
        "EIE saw no /v1/execute: Gate did not dispatch the CEG request to the real EIE process"
    )
    payload = dispatch.get("payload", {})
    # Transport is what this seam proves. The enrichment *domain* result depends
    # on an LLM provider that is deliberately absent here; report it, do not assume it.
    domain_state = payload.get("state", "UNKNOWN")
    assert "state" in payload or dispatch["packet_type"] == "failure", (
        f"EIE did not answer with an EnrichResponse-shaped payload: {payload}"
    )
    evidence.record(
        "B-01",
        direction="CEG->Gate->EIE",
        status="PASS",
        action="enrich",
        detail="CEG engine.gate_egress.request_enrichment (production path) sent `enrich`; Gate dispatched to EIE; EIE's enrich handler answered",
        transport_status=dispatch.get("status"),
        packet_type=dispatch["packet_type"],
        packet_id=dispatch["packet_id"],
        idempotency_key=dispatch.get("idempotency_key"),
        domain_state=domain_state,
        domain_failure_reason=payload.get("failure_reason"),
        provider_note="no LLM provider credentials configured in this environment; domain result is reported as observed",
    )


def test_b2_ceg_health_trigger_dispatches_through_gate(
    ctx: SeamContext,
    constellation: dict,
    eie: ManagedProcess,
    ceg_spec_path: Path,
    evidence: Evidence,
) -> None:
    eie_before = execute_hits(eie)
    entity_health = {
        "entity_id": f"{ENTITY_ID}-trigger",
        "domain": TENANT,
        "readiness_score": 20.0,
        "grade": "F",
        "critical_gaps": ["website", "polymer_type"],
        "enrichment_targets": [
            {"field_name": "website", "priority_score": 95.0, "is_gate_critical": True},
            {"field_name": "polymer_type", "priority_score": 90.0, "is_gate_critical": True},
        ],
        "gate_completeness": 0.0,
        "scoring_dimension_coverage": 0.0,
    }
    result = ceg_call(ctx, ceg_spec_path, op="trigger", tenant=TENANT, entity_health=entity_health)
    outcome = result["result"]
    assert outcome.get("recommendation") == "enrich_now", outcome.get("priority")
    dispatch = outcome.get("dispatch") or {}
    assert dispatch.get("packet_id"), f"trigger did not dispatch through Gate: {outcome}"
    time.sleep(0.3)
    assert execute_hits(eie) > eie_before
    evidence.record(
        "B-02",
        direction="CEG->Gate->EIE",
        status="PASS",
        action="enrich",
        detail="CEG ROI health trigger (trigger_reenrichment_v2) now really dispatches through Gate to EIE instead of returning an unsent payload",
        triggered=outcome.get("triggered"),
        packet_id=dispatch.get("packet_id"),
        packet_type=dispatch.get("packet_type"),
    )
