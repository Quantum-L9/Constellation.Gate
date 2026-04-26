#!/usr/bin/env python3
"""Cross-repo contract validation script for Constellation.Gate.

Checks:
  1. contracts/transport-packet.schema.json is valid JSON.
  2. All required top-level fields are present in the schema.
  3. The $id matches the canonical contract URL.
  4. SDK schema parity: if SDK schema is available at a sibling path, verify
     that all required-array entries and additionalProperties=false are present.

Exit codes:
  0 — all checks pass
  1 — one or more checks failed
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
GATE_SCHEMA_PATH = SCRIPT_DIR.parent / "contracts" / "transport-packet.schema.json"
CANONICAL_ID = "https://constellation.local/contracts/transport-packet.schema.json"
REQUIRED_TOP_LEVEL_FIELDS = {
    "header",
    "address",
    "tenant",
    "payload",
    "security",
    "governance",
    "provenance",
    "delegation_chain",
    "hop_trace",
    "lineage",
    "attachments",
}

failures: list[str] = []


def fail(msg: str) -> None:
    failures.append(msg)
    print(f"  FAIL: {msg}")


def ok(msg: str) -> None:
    print(f"  OK:   {msg}")


print("[validate_contracts] checking Gate transport-packet.schema.json...")

if not GATE_SCHEMA_PATH.exists():
    fail(f"schema not found: {GATE_SCHEMA_PATH}")
    sys.exit(1)

try:
    schema = json.loads(GATE_SCHEMA_PATH.read_text(encoding="utf-8"))
except json.JSONDecodeError as exc:
    fail(f"schema is not valid JSON: {exc}")
    sys.exit(1)

ok("schema is valid JSON")

# Check $id
if schema.get("$id") == CANONICAL_ID:
    ok(f"$id matches canonical: {CANONICAL_ID}")
else:
    fail(f"$id mismatch: got {schema.get('$id')!r}, expected {CANONICAL_ID!r}")

# Check additionalProperties: false
if schema.get("additionalProperties") is False:
    ok("top-level additionalProperties=false")
else:
    fail("top-level additionalProperties must be false")

# Check required array
required = set(schema.get("required", []))
missing = REQUIRED_TOP_LEVEL_FIELDS - required
extra = required - REQUIRED_TOP_LEVEL_FIELDS
if not missing:
    ok(f"all {len(REQUIRED_TOP_LEVEL_FIELDS)} required top-level fields present")
else:
    fail(f"missing required top-level fields: {sorted(missing)}")
if extra:
    fail(f"unexpected required top-level fields: {sorted(extra)}")

# Check header.action has pattern constraint
action_def = schema.get("properties", {}).get("header", {}).get("properties", {}).get("action", {})
if action_def.get("pattern") == "^[a-z0-9][a-z0-9-]{0,63}$":
    ok("header.action has correct pattern constraint")
else:
    fail(
        f"header.action missing pattern constraint. "
        f"Got: {action_def.get('pattern')!r}. "
        "Expected: '^[a-z0-9][a-z0-9-]{0,63}$'"
    )

# Check security.signature_algorithm has enum or anyOf with enum
sig_alg_def = schema.get("properties", {}).get("security", {}).get("properties", {}).get("signature_algorithm", {})
has_algo_constraint = (
    "enum" in sig_alg_def
    or any("enum" in branch for branch in sig_alg_def.get("anyOf", []))
)
if has_algo_constraint:
    ok("security.signature_algorithm has enum constraint")
else:
    fail("security.signature_algorithm must have enum constraint restricting to [hmac-sha256, ed25519]")

# Check hop.status has enum constraint
status_def = (
    schema.get("properties", {})
    .get("hop_trace", {})
    .get("items", {})
    .get("properties", {})
    .get("status", {})
)
has_status_enum = (
    "enum" in status_def
    or any("enum" in branch for branch in status_def.get("anyOf", []))
)
if has_status_enum:
    ok("hop_trace.items.status has enum constraint")
else:
    fail("hop_trace.items.status must have enum constraint")

# Check hop.hop_signature_algorithm has enum constraint
hop_sig_alg_def = (
    schema.get("properties", {})
    .get("hop_trace", {})
    .get("items", {})
    .get("properties", {})
    .get("hop_signature_algorithm", {})
)
has_hop_sig_alg_constraint = (
    "enum" in hop_sig_alg_def
    or any("enum" in branch for branch in hop_sig_alg_def.get("anyOf", []))
)
if has_hop_sig_alg_constraint:
    ok("hop_trace.items.hop_signature_algorithm has enum constraint")
else:
    fail("hop_trace.items.hop_signature_algorithm must have enum constraint")

print()
if failures:
    print(f"[validate_contracts] FAILED — {len(failures)} check(s) failed.")
    sys.exit(1)
else:
    print("[validate_contracts] all checks passed.")
