#!/usr/bin/env python3
"""CEG -> Gate -> EIE, driven by CEG's OWN production egress code.

Runs inside the running `graph` container. It calls
`engine.gate_egress.request_enrichment` -- the module CEG ships and would use
in production -- rather than hand-rolling an SDK call, so what is proven is
that CEG's application egress reaches EIE through Gate over real container
networking.

Why it has to be invoked directly: `request_enrichment`'s only in-repo caller
chain is engine/health/api.py -> trigger_reenrichment_v2, and nothing imports
engine.health.api (and settings.auto_enrich_via_gate defaults False). The
outbound path is implemented but has no reachable inbound trigger in the
current source, so no packet arriving at CEG can cause it to fire. This probe
mirrors what the existing process-rail seam harness does with its CEG_DRIVER.

Emits one JSON object on stdout.
"""

from __future__ import annotations

import asyncio
import json
import sys
import traceback


async def main() -> None:
    out: dict = {"check": "P5_ceg_to_gate_to_eie"}
    try:
        from engine.gate_egress import request_enrichment

        result = await request_enrichment(
            tenant="plasticos",
            entity_id="E2E-CEG-EGRESS-1",
            domain="plasticos",
            target_fields=["grade"],
            entity={"facility_id": "E2E-CEG-EGRESS-1"},
        )
        out["raw_result"] = result
        # Affirmative proof only. An earlier version inferred success from the
        # ABSENCE of a few known transport errors, so a None return or any
        # unlisted error read as PASS -- the probe could report the hop
        # succeeded when CEG never reached Gate at all, and assert_evidence
        # trusts this status directly. Require positive evidence instead:
        # Gate returned a response packet AND EIE's handler actually ran.
        payload = result.get("payload") if isinstance(result, dict) else None
        payload = payload if isinstance(payload, dict) else {}
        checks = {
            "result_is_dict": isinstance(result, dict),
            "status_ok": isinstance(result, dict) and result.get("status") == "ok",
            "response_packet": isinstance(result, dict) and result.get("packet_type") == "response",
            "packet_id_present": bool(isinstance(result, dict) and result.get("packet_id")),
            # Only EIE's enrichment handler produces these.
            "eie_handler_ran": "inference_version" in payload and "processing_time_ms" in payload,
        }
        out["checks"] = checks
        out["reached_eie"] = all(checks.values())
        out["status"] = "PASS" if out["reached_eie"] else "FAIL"
        out["eie_inference_version"] = payload.get("inference_version")
        # The business outcome needs a live provider; the transport hop does
        # not. Report it rather than folding it into the verdict.
        out["business_state"] = payload.get("state")
        out["business_failure_reason"] = payload.get("failure_reason")
    except Exception as exc:  # noqa: BLE001 - probe must report, not raise
        out["status"] = "ERROR"
        out["error"] = f"{type(exc).__name__}: {exc}"
        out["trace"] = traceback.format_exc()[-1500:]
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    asyncio.run(main())
    sys.exit(0)
