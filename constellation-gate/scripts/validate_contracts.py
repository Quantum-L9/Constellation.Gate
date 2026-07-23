#!/usr/bin/env python3
"""Cross-repo contract validation script for Constellation.Gate.

Checks:
  1. contracts/transport-packet.schema.json is valid JSON.
  2. All required top-level fields are present in the schema.
  3. The $id matches the canonical contract URL.
  4. Constraint invariants: header.action pattern, and exact enum membership for
     security.signature_algorithm, hop_trace.items.status, and
     hop_trace.items.hop_signature_algorithm.

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


def _enum_values(definition: dict) -> set[str] | None:
    """Collect enum members from a definition or its anyOf branches; None if absent."""
    if "enum" in definition:
        return {v for v in definition["enum"] if isinstance(v, str)}
    branches = [b for b in definition.get("anyOf", []) if "enum" in b]
    if branches:
        return {v for b in branches for v in b["enum"] if isinstance(v, str)}
    return None


def check_enum(label: str, definition: dict, expected: set[str]) -> None:
    """Fail unless the definition's enum members exactly match the expected set."""
    values = _enum_values(definition)
    if values is None:
        fail(f"{label} must have enum constraint restricting to {sorted(expected)}")
    elif values != expected:
        fail(f"{label} enum drift: got {sorted(values)}, expected {sorted(expected)}")
    else:
        ok(f"{label} enum matches {sorted(expected)}")


# Check security.signature_algorithm enum members exactly
sig_alg_def = (
    schema.get("properties", {})
    .get("security", {})
    .get("properties", {})
    .get("signature_algorithm", {})
)
check_enum("security.signature_algorithm", sig_alg_def, {"hmac-sha256", "ed25519"})

# Check hop.status has enum constraint
status_def = (
    schema.get("properties", {})
    .get("hop_trace", {})
    .get("items", {})
    .get("properties", {})
    .get("status", {})
)
status_enum = _enum_values(status_def)
if status_enum is None:
    fail("hop_trace.items.status must have enum constraint")
elif not status_enum:
    fail("hop_trace.items.status enum must not be empty")
else:
    ok(f"hop_trace.items.status has enum constraint: {sorted(status_enum)}")

# Check hop.hop_signature_algorithm has enum constraint
hop_sig_alg_def = (
    schema.get("properties", {})
    .get("hop_trace", {})
    .get("items", {})
    .get("properties", {})
    .get("hop_signature_algorithm", {})
)
check_enum(
    "hop_trace.items.hop_signature_algorithm",
    hop_sig_alg_def,
    {"hmac-sha256", "ed25519"},
)

print()
if failures:
    print(f"[validate_contracts] FAILED — {len(failures)} check(s) failed.")
    sys.exit(1)
else:
    print("[validate_contracts] all checks passed.")
