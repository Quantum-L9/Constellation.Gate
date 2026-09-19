#!/usr/bin/env python3
"""Keep signing material out of the evidence bundle.

Two modes:

  redact.py <src> <dst> <env-file>
      Copy src to dst with every secret value from env-file replaced.
      `<src>` may be "-" to read stdin, which is how `docker compose config`
      is consumed: it interpolates variables, so its output carries the run's
      signing keys and admin token in plaintext. Streaming it means the
      unredacted form is never written to disk at all.

  redact.py --scan <bundle-dir> <env-file>
      Walk a finished bundle and report any file still containing a secret.
      Printed into the bundle as secret_scan.txt and gated by assert_evidence.

Key IDs (gate-e2e, eie-e2e, ceg-e2e) are NOT secrets and are deliberately kept:
they are what makes the signing evidence meaningful.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PLACEHOLDER = "***REDACTED-BY-L9-E2E***"

# Values of these variables are secret. The verifying-key map is JSON whose
# *values* are the same secrets, so it is expanded rather than matched whole.
SECRET_VARS = {
    "L9E2E_GATE_KEY",
    "L9E2E_EIE_KEY",
    "L9E2E_CEG_KEY",
    "L9E2E_ADMIN_TOKEN",
    "L9E2E_NEO4J_PASSWORD",
    "L9E2E_PG_PASSWORD",
}
JSON_MAP_VARS = {"L9E2E_VERIFYING_KEYS_JSON"}


def secrets_from(env_file: Path) -> set[str]:
    found: set[str] = set()
    for line in env_file.read_text().splitlines():
        key, _, raw = line.strip().partition("=")
        val = raw.strip().strip("'").strip('"')
        if not val:
            continue
        if key in SECRET_VARS:
            found.add(val)
        elif key in JSON_MAP_VARS:
            try:
                for v in json.loads(val).values():
                    if isinstance(v, str) and v:
                        found.add(v)
            except Exception:
                found.add(val)
    return found


def redact_text(body: str, secrets: set[str]) -> str:
    # Longest first so a secret that contains another is replaced whole.
    for s in sorted(secrets, key=len, reverse=True):
        body = body.replace(s, PLACEHOLDER)
    return body


def mode_redact(src: Path, dst: Path, env_file: Path) -> int:
    secrets = secrets_from(env_file)
    # "-" streams stdin so an unredacted copy never touches the filesystem.
    body = sys.stdin.read() if str(src) == "-" else src.read_text(errors="replace")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(redact_text(body, secrets))
    print(f"redacted {'<stdin>' if str(src) == '-' else src} -> {dst} "
          f"({len(secrets)} secret values)")
    return 0


def mode_scan(bundle: Path, env_file: Path) -> int:
    secrets = secrets_from(env_file)
    leaks: list[str] = []
    for f in sorted(bundle.rglob("*")):
        if not f.is_file() or f.name == "secret_scan.txt":
            continue
        try:
            body = f.read_text(errors="replace")
        except Exception:
            continue
        for s in secrets:
            if s in body:
                leaks.append(str(f.relative_to(bundle)))
                break
    if leaks:
        print("LEAKS: " + ", ".join(leaks))
        return 1
    print(f"LEAKS: none — {len(secrets)} secret values checked across the bundle")
    return 0


def main() -> int:
    if sys.argv[1:2] == ["--scan"]:
        return mode_scan(Path(sys.argv[2]), Path(sys.argv[3]))
    return mode_redact(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))


if __name__ == "__main__":
    raise SystemExit(main())
