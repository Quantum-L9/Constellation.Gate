#!/usr/bin/env python3
"""Turn one evidence bundle into a single verdict.

A mandatory scenario that did not run is a FAIL, never a pass -- the absence of
a result is treated as the absence of proof.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

MANDATORY = [
    ("P1_gate_to_eie", "signed client -> Gate -> EIE"),
    ("P2_gate_to_ceg_sync", "signed client -> Gate -> CEG (Neo4j write)"),
    ("P3_gate_to_ceg_match", "signed client -> Gate -> CEG (match)"),
    ("P4_replay_same_packet", "replay of an identical signed packet"),
    ("N1_unsigned_rejected", "unsigned packet refused"),
    ("N2_bad_signature_rejected", "wrong-key signature refused"),
    ("N3_unknown_action_404", "unowned action -> 404"),
    ("N4_destination_override_refused", "client cannot name a worker"),
]


def load(p: Path):
    """Return the LAST top-level JSON object in the file.

    Probes run inside application containers whose logging writes to stdout, so
    a result file can carry log lines -- themselves sometimes JSON -- before the
    result. Treating that as unparseable would report a scenario that actually
    ran as MISSING, and taking the FIRST object would report a log line as the
    result. Scan every top-level object with raw_decode and keep the last.
    """
    try:
        raw = p.read_text()
    except Exception:
        return None
    try:
        return json.loads(raw)
    except Exception:
        pass
    decoder = json.JSONDecoder()
    last = None
    idx = raw.find("{")
    while idx != -1:
        try:
            obj, end = decoder.raw_decode(raw, idx)
        except ValueError:
            idx = raw.find("{", idx + 1)
            continue
        if isinstance(obj, dict):
            last = obj
        idx = raw.find("{", max(end, idx + 1))
    return last


def main() -> int:
    ev = Path(sys.argv[1])
    results: dict[str, str] = {}

    main_flows = load(ev / "flows" / "main.json") or {}
    for key, _label in MANDATORY:
        got = main_flows.get(key)
        results[key] = got.get("status") if isinstance(got, dict) else "MISSING"

    for fname, key in (
        ("outage.json", "N5_worker_down_fails_closed"),
        ("recovery.json", "P2_gate_to_ceg_sync"),
    ):
        d = load(ev / "flows" / fname) or {}
        rk = key if fname == "outage.json" else "P7_recovery_after_restart"
        got = d.get(key)
        results[rk] = got.get("status") if isinstance(got, dict) else "MISSING"

    for fname, key in (
        ("eie_to_ceg.json", "P6_eie_to_gate_to_ceg"),
        ("ceg_to_eie.json", "P5_ceg_to_gate_to_eie"),
    ):
        d = load(ev / "flows" / fname) or {}
        results[key] = d.get("status", "MISSING") if isinstance(d, dict) else "MISSING"

    iso = load(ev / "flows" / "isolation.json") or {}
    results["N6_peer_isolation"] = iso.get("verdict", "MISSING")

    reg = load(ev / "gate_registry.json") or {}
    results["REG_live_registration"] = (
        "PASS" if {"enrichment-engine", "graph"} <= set(reg) else "FAIL"
    )

    sdk = load(ev / "sdk_provenance.json") or {}
    commits, sources = {}, {}
    for node, info in sdk.items():
        du = (info or {}).get("direct_url") or {}
        cid = (du.get("vcs_info") or {}).get("commit_id")
        if cid:
            commits[node], sources[node] = cid, "container_dist_info"
        elif (info or {}).get("vendored_commit_id"):
            commits[node] = info["vendored_commit_id"]
            sources[node] = "vendoring_receipt (pip records file:// for a path install)"
        else:
            commits[node], sources[node] = None, "unresolved"
    results["SDK_provenance_captured"] = (
        "PASS" if all(commits.get(n) for n in ("gate", "eie", "ceg")) else "FAIL"
    )

    persisted = ev / "flows" / "neo4j_state.txt"
    body = persisted.read_text() if persisted.exists() else ""
    results["PERSIST_neo4j_effect"] = (
        "PASS" if "E2E-EIE-EGRESS-1" in body and "E2E-F-001" in body else "FAIL"
    )

    scan = ev / "secret_scan.txt"
    scan_body = scan.read_text() if scan.exists() else "MISSING"
    results["EVIDENCE_no_secrets"] = "PASS" if "LEAKS: none" in scan_body else "FAIL"

    failed = [k for k, v in results.items() if v != "PASS"]
    verdict = "PASS" if not failed else "FAIL"

    out = {
        "verdict": verdict,
        "results": results,
        "sdk_commits": commits,
        "sdk_commit_sources": sources,
        "failed_checks": failed,
    }
    (ev / "assertions.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
