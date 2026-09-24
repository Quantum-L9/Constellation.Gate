#!/usr/bin/env python3
"""EIE -> Gate -> CEG, driven by EIE's OWN production egress code.

Runs inside the running `enrichment-engine` container. It calls
`app.engines.packet_router.get_router(...).notify_graph_sync(...)` -- the exact
call site that EIE's `enrich` handler reaches via `_persist_and_sync` ->
`side_effect_coordinator.commit_after_enrich`. Nothing is hand-rolled: the
packet, signing, Gate destination and retry policy are all EIE's.

Why it is invoked directly rather than by sending EIE an `enrich` packet: the
`_persist_and_sync` branch runs only when enrichment returns
`state == "completed"`, which requires a reachable Perplexity endpoint. With no
provider egress the enrich path short-circuits to `state == "failed"` and never
reaches the graph-sync call. Driving the router directly exercises the same
production code over the same real network path, which is what the transport
rail is meant to prove. This mirrors the existing process-rail seam harness's
EIE_DRIVER `sync` op.

Emits one JSON object on stdout.
"""

from __future__ import annotations

import asyncio
import json
import traceback


async def main() -> None:
    out: dict = {"check": "P6_eie_to_gate_to_ceg"}
    try:
        from app.core.config import get_settings
        from app.engines.packet_router import get_router

        router = get_router(get_settings())
        result = await router.notify_graph_sync(
            tenant_id="plasticos",
            entity_id="E2E-EIE-EGRESS-1",
            fields={"name": "EIE Egress Facility", "e2e_marker": "eie-to-ceg"},
            domain="plasticos",
        )
        out["raw_result"] = result
        ok = isinstance(result, dict) and str(result.get("status", "")).lower() in {
            "success",
            "ok",
        }
        out["status"] = "PASS" if ok else "FAIL"
    except Exception as exc:  # noqa: BLE001 - probe must report, not raise
        out["status"] = "ERROR"
        out["error"] = f"{type(exc).__name__}: {exc}"
        out["trace"] = traceback.format_exc()[-1500:]
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    asyncio.run(main())
