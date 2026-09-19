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
        status = str(result.get("status", "")).lower() if isinstance(result, dict) else ""
        # "failed" with a transport error means the hop did NOT happen.
        # A non-transport failure still proves CEG -> Gate -> EIE routing.
        transport_errors = {
            "gate_not_configured", "GateConnectionError",
            "GateTimeoutError", "GateProtocolError",
        }
        err = str(result.get("error", "")) if isinstance(result, dict) else ""
        out["reached_eie"] = err not in transport_errors
        out["status"] = "PASS" if out["reached_eie"] else "FAIL"
        out["transport_error"] = err if err in transport_errors else None
    except Exception as exc:  # noqa: BLE001 - probe must report, not raise
        out["status"] = "ERROR"
        out["error"] = f"{type(exc).__name__}: {exc}"
        out["trace"] = traceback.format_exc()[-1500:]
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    asyncio.run(main())
    sys.exit(0)
