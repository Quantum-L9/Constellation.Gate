#!/usr/bin/env python3
"""Scenario driver for the Constellation Docker system E2E.

Runs INSIDE a container on the control network. It reaches the system only
through Gate; it never calls a worker's HTTP port during positive scenarios.

Positive scenarios use the SDK's real GateClient -- the same transport the
nodes themselves use. Adversarial scenarios take a genuine signed packet and
mutate exactly one property of it (signature removed, signature corrupted,
destination overridden), so the thing under test is the single deviation and
nothing else.

Results go to stdout as one JSON object. Secrets are never printed.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import traceback
from typing import Any

import httpx
from constellation_node_sdk.gate.client import GateClient
from constellation_node_sdk.gate.config import GateClientConfig
from constellation_node_sdk.security.signing import sign_transport_packet
from constellation_node_sdk.transport.packet import create_transport_packet

GATE_URL = os.environ["GATE_URL"].rstrip("/")
VERIFYING = json.loads(os.environ["L9_VERIFYING_KEYS_JSON"])
DRIVER_KEY = os.environ["L9E2E_DRIVER_KEY"]
DRIVER_KEY_ID = os.environ.get("L9E2E_DRIVER_KEY_ID", "gate-e2e")
TENANT = os.environ.get("L9E2E_TENANT", "plasticos")

RESULTS: dict[str, Any] = {}


def record(check: str, **kw: Any) -> None:
    RESULTS[check] = kw
    print(f"[{check}] {kw.get('status')}", file=sys.stderr)


def client_config() -> GateClientConfig:
    # Built explicitly rather than from env: the SDK revision pinned by Gate's
    # requirements.lock (2b2f53a2) hardcodes verifying_keys={} in
    # get_gate_client_config_from_env(), so an env-built client in THIS image
    # could not resolve Gate's response key. Constructing the config directly
    # exercises the same client code without that defect masking the result.
    return GateClientConfig(
        gate_url=GATE_URL,
        local_node="e2e-driver",
        require_signature=True,
        signing_key=DRIVER_KEY,
        signing_key_id=DRIVER_KEY_ID,
        signing_algorithm="hmac-sha256",
        verify_response_signatures=True,
        verifying_keys=VERIFYING,
    )


def signed_packet(action: str, payload: dict, *, destination: str = "gate") -> Any:
    pkt = create_transport_packet(
        action=action,
        payload=payload,
        tenant=TENANT,
        destination_node=destination,
        source_node="e2e-driver",
        reply_to="e2e-driver",
    )
    return sign_transport_packet(pkt, key=DRIVER_KEY, key_id=DRIVER_KEY_ID, algorithm="hmac-sha256")


async def post_raw(body: dict) -> httpx.Response:
    async with httpx.AsyncClient(timeout=30.0) as c:
        return await c.post(f"{GATE_URL}/v1/execute", json=body)


# ───────────────────────────── positive scenarios ─────────────────────────────


async def p_gate_to_eie() -> None:
    """client -> Gate -> EIE, via an action EIE owns that needs no external API."""
    try:
        gc = GateClient(client_config())
        resp = await gc.execute(
            action="graph-inference-result",
            tenant=TENANT,
            payload={
                "inference_outputs": [
                    {
                        "entity_id": "E2E-1",
                        "field": "grade",
                        "value": "HDPE-A",
                        "confidence": 0.93,
                        "rule": "e2e",
                    }
                ]
            },
        )
        ok = resp.header.packet_type == "response" and resp.payload.get("status") == "accepted"
        record(
            "P1_gate_to_eie",
            status="PASS" if ok else "FAIL",
            packet_type=resp.header.packet_type,
            action=resp.header.action,
            source_node=resp.address.source_node,
            reply_to=resp.address.reply_to,
            signing_key_id=resp.security.signing_key_id,
            signature_present=resp.security.signature is not None,
            correlation_id=str(resp.header.correlation_id),
            payload=resp.payload,
        )
    except Exception as exc:
        record(
            "P1_gate_to_eie",
            status="FAIL",
            error=f"{type(exc).__name__}: {exc}",
            trace=traceback.format_exc()[-1200:],
        )


async def p_gate_to_ceg_sync() -> None:
    """client -> Gate -> CEG `sync`, which MERGEs a node into Neo4j."""
    try:
        gc = GateClient(client_config())
        resp = await gc.execute(
            action="sync",
            tenant=TENANT,
            payload={
                "entity_type": "facilities",
                "batch": [
                    {
                        "facility_id": "E2E-F-001",
                        "name": "E2E Facility",
                        "e2e_marker": "docker-rail",
                    }
                ],
            },
            idempotency_key="e2e:sync:facility:001",
        )
        ok = resp.header.packet_type == "response" and str(
            resp.payload.get("status", "")
        ).lower() in {"success", "ok", "accepted"}
        record(
            "P2_gate_to_ceg_sync",
            status="PASS" if ok else "FAIL",
            packet_type=resp.header.packet_type,
            source_node=resp.address.source_node,
            signing_key_id=resp.security.signing_key_id,
            signature_present=resp.security.signature is not None,
            payload=resp.payload,
        )
    except Exception as exc:
        record(
            "P2_gate_to_ceg_sync",
            status="FAIL",
            error=f"{type(exc).__name__}: {exc}",
            trace=traceback.format_exc()[-1200:],
        )


async def p_gate_to_ceg_match() -> None:
    try:
        gc = GateClient(client_config())
        resp = await gc.execute(
            action="match",
            tenant=TENANT,
            payload={
                "match_direction": "supply_opportunity_to_buyer_facility",
                "query": {"polymer_type": "HDPE"},
                "top_n": 5,
            },
        )
        ok = resp.header.packet_type == "response" and "candidates" in resp.payload
        record(
            "P3_gate_to_ceg_match",
            status="PASS" if ok else "FAIL",
            packet_type=resp.header.packet_type,
            source_node=resp.address.source_node,
            payload_keys=sorted(resp.payload),
            payload=resp.payload if not ok else None,
            total_candidates=resp.payload.get("total_candidates"),
        )
    except Exception as exc:
        record("P3_gate_to_ceg_match", status="FAIL", error=f"{type(exc).__name__}: {exc}")


# ──────────────────────────── adversarial scenarios ───────────────────────────


async def n_unsigned() -> None:
    """A structurally valid packet with the signature removed must be refused."""
    try:
        pkt = signed_packet(
            "sync", {"entity_type": "facilities", "batch": [{"facility_id": "E2E-UNSIGNED"}]}
        )
        body = json.loads(pkt.model_dump_json())
        body["security"]["signature"] = None
        body["security"]["signing_key_id"] = None
        body["security"]["signature_algorithm"] = None
        r = await post_raw(body)
        record(
            "N1_unsigned_rejected",
            status="PASS" if r.status_code in (400, 401, 403) else "FAIL",
            http_status=r.status_code,
            body=r.text[:400],
        )
    except Exception as exc:
        record("N1_unsigned_rejected", status="ERROR", error=f"{type(exc).__name__}: {exc}")


async def n_bad_signature() -> None:
    """Same packet, signature replaced with one produced by an unknown key."""
    try:
        pkt = signed_packet(
            "sync", {"entity_type": "facilities", "batch": [{"facility_id": "E2E-BADSIG"}]}
        )
        body = json.loads(pkt.model_dump_json())
        body["security"]["signature"] = "de" * 32  # well-formed hex, wrong key
        r = await post_raw(body)
        record(
            "N2_bad_signature_rejected",
            status="PASS" if r.status_code in (400, 401, 403) else "FAIL",
            http_status=r.status_code,
            body=r.text[:400],
        )
    except Exception as exc:
        record("N2_bad_signature_rejected", status="ERROR", error=f"{type(exc).__name__}: {exc}")


async def n_unknown_action() -> None:
    """An action no node advertises must be a permanent 404, not a 503."""
    try:
        pkt = signed_packet("graph-query", {"q": 1})
        r = await post_raw(json.loads(pkt.model_dump_json()))
        record(
            "N3_unknown_action_404",
            status="PASS" if r.status_code == 404 else "FAIL",
            http_status=r.status_code,
            body=r.text[:300],
        )
    except Exception as exc:
        record("N3_unknown_action_404", status="ERROR", error=f"{type(exc).__name__}: {exc}")


async def n_destination_override() -> None:
    """A client must not be able to name a worker and bypass Gate's ownership
    decision. `sync` is CEG-owned; address it explicitly at enrichment-engine."""
    try:
        pkt = signed_packet(
            "sync",
            {"entity_type": "facilities", "batch": [{"facility_id": "E2E-HIJACK"}]},
            destination="enrichment-engine",
        )
        r = await post_raw(json.loads(pkt.model_dump_json()))
        ok = r.status_code >= 400
        record(
            "N4_destination_override_refused",
            status="PASS" if ok else "FAIL",
            http_status=r.status_code,
            body=r.text[:400],
        )
    except Exception as exc:
        record(
            "N4_destination_override_refused", status="ERROR", error=f"{type(exc).__name__}: {exc}"
        )


async def n_worker_down() -> None:
    """Run only in the outage phase: CEG is stopped, so a CEG-owned action must
    fail closed at Gate (503/502/504) with no direct-peer fallback."""
    try:
        pkt = signed_packet(
            "sync", {"entity_type": "facilities", "batch": [{"facility_id": "E2E-OUTAGE"}]}
        )
        r = await post_raw(json.loads(pkt.model_dump_json()))
        record(
            "N5_worker_down_fails_closed",
            status="PASS" if r.status_code in (502, 503, 504) else "FAIL",
            http_status=r.status_code,
            body=r.text[:400],
        )
    except Exception as exc:
        record("N5_worker_down_fails_closed", status="ERROR", error=f"{type(exc).__name__}: {exc}")


async def p_replay_idempotency() -> None:
    """The identical signed packet delivered twice must not double-apply."""
    try:
        pkt = signed_packet(
            "sync",
            {
                "entity_type": "facilities",
                "batch": [{"facility_id": "E2E-REPLAY", "name": "Replay Target"}],
            },
        )
        body = json.loads(pkt.model_dump_json())
        r1 = await post_raw(body)
        r2 = await post_raw(body)
        first_type = (
            r1.json().get("header", {}).get("packet_type") if r1.status_code == 200 else None
        )
        ok = r1.status_code == 200 and first_type == "response" and r2.status_code in (400, 409)
        record(
            "P4_replay_same_packet",
            status="PASS" if ok else "FAIL",
            first=r1.status_code,
            first_packet_type=first_type,
            second=r2.status_code,
            second_body=r2.text[:300],
        )
    except Exception as exc:
        record("P4_replay_same_packet", status="ERROR", error=f"{type(exc).__name__}: {exc}")


PHASES = {
    "main": [
        p_gate_to_eie,
        p_gate_to_ceg_sync,
        p_gate_to_ceg_match,
        p_replay_idempotency,
        n_unsigned,
        n_bad_signature,
        n_unknown_action,
        n_destination_override,
    ],
    "outage": [n_worker_down],
    "recovery": [p_gate_to_ceg_sync],
}


async def main() -> None:
    phase = sys.argv[1] if len(sys.argv) > 1 else "main"
    for fn in PHASES[phase]:
        await fn()
    print(json.dumps(RESULTS, indent=1, default=str))


if __name__ == "__main__":
    asyncio.run(main())
