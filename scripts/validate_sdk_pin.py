#!/usr/bin/env python3
"""Every Gate_SDK reference in this repository must name the one pinned commit.

Checking pyproject.toml alone was not enough: the lock that builds the
container image named 2b2f53a (an SDK without the L9_VERIFYING_KEYS_JSON
GateClientConfig fix) and the pre-commit mypy hook named 0d50f64 (~2.6k src/
lines behind, transport/packet.py included), while pyproject named a third
commit. Three pins, three different transport contracts, nothing comparing
them. This scans every known pin site for *any* Gate_SDK sha and fails on
whichever one disagrees, so the drift cannot come back silently.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN = "e20f6c4ef71cd82f3a4cf6152b1090286e9970c4"

# Both spellings a pin site can use: the git+https requirement and the GitHub
# source-archive URL that requirements.lock needs in order to be hash-verified.
SDK_SHA = re.compile(
    r"Gate_SDK(?:\.git@|/archive/)(?P<sha>[0-9a-f]{40})",
    re.IGNORECASE,
)
FLOATING = re.compile(r"Gate_SDK\.git@(?!\s*[0-9a-f]{40})\S+", re.IGNORECASE)

PIN_SITES = (
    "constellation-gate/pyproject.toml",
    "constellation-gate/requirements.lock",
    "constellation-gate/.pre-commit-config.yaml",
)

errors: list[str] = []

for relative in PIN_SITES:
    path = ROOT / relative
    if not path.exists():
        errors.append(f"{relative}: pin site is missing")
        continue
    text = path.read_text(encoding="utf-8")
    found = {match.group("sha").lower() for match in SDK_SHA.finditer(text)}
    if not found:
        errors.append(f"{relative}: no Gate_SDK commit pin found")
    for sha in sorted(found - {PIN}):
        errors.append(f"{relative}: pins {sha}, expected {PIN}")
    for match in FLOATING.finditer(text):
        errors.append(f"{relative}: floating ref {match.group(0)!r} (pin a 40-hex commit)")

if errors:
    print("FAIL")
    print("\n".join(errors))
    raise SystemExit(1)

print("PASS: Gate SDK pin", PIN, f"({len(PIN_SITES)} sites agree)")
