#!/usr/bin/env python3
"""Render a build-time Dockerfile that trusts the session's egress-proxy CA.

WHY THIS EXISTS
---------------
This sandbox terminates TLS at an agent proxy, so *every* outbound HTTPS
connection from inside a container -- pypi.org and github.com included -- is
presented a certificate signed by a CA that upstream base images do not trust.
A stock `python:3.12-slim` therefore cannot `pip install` anything here.

The repository Dockerfiles are NOT modified on disk. This script reads a repo
Dockerfile and emits a derived one that inserts a CA-trust layer immediately
after every `FROM` instruction. Every other instruction -- every dependency
resolution, every install, every COPY, the entrypoint -- is preserved
byte-identically and in order.

The CA file is supplied through a BuildKit *named context* (`--build-context
l9ca=...`) rather than by copying it into the repository tree, so no repo
working tree is touched and `.dockerignore` is not involved.

This is an environment accommodation, not a product change, and it is recorded
as such in the evidence bundle (`image_provenance.json:ca_injection`). It does
mean the built images differ from a pristine production build by exactly one
added CA certificate per stage.
"""

from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path

# Inserted verbatim after each FROM. `USER root` guards against a base image
# that already dropped privileges; update-ca-certificates needs to write to
# /etc/ssl/certs. The ENV block points the toolchains that do NOT read the
# system store (pip, requests, git) at the merged bundle.
CA_LAYER = """
# --- l9-e2e CA trust (injected by tests/e2e/docker/scripts/ca_inject.py) ---
USER root
COPY --from=l9ca ca-bundle.crt /usr/local/share/ca-certificates/l9-egress-proxy.crt
RUN update-ca-certificates
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \\
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \\
    PIP_CERT=/etc/ssl/certs/ca-certificates.crt \\
    GIT_SSL_CAINFO=/etc/ssl/certs/ca-certificates.crt \\
    CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
# --- end l9-e2e CA trust ---
"""

# A FROM line, capturing any `AS <stage>` alias. Continuation lines are not a
# concern: FROM does not take one.
FROM_RE = re.compile(r"^\s*FROM\s+", re.IGNORECASE)


def render(source: Path) -> tuple[str, int]:
    """Return (rendered Dockerfile text, number of FROM stages patched)."""
    lines = source.read_text(encoding="utf-8").splitlines(keepends=True)
    out: list[str] = []
    patched = 0
    for line in lines:
        out.append(line)
        if FROM_RE.match(line):
            if not line.endswith("\n"):
                out.append("\n")
            out.append(CA_LAYER)
            patched += 1
    if patched == 0:
        msg = f"no FROM instruction found in {source}"
        raise SystemExit(msg)
    return "".join(out), patched


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", required=True, type=Path, help="repository Dockerfile (never modified)")
    ap.add_argument("--out", required=True, type=Path, help="rendered Dockerfile to write")
    args = ap.parse_args()

    original = args.src.read_bytes()
    rendered, patched = render(args.src)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(rendered, encoding="utf-8")

    print(f"src={args.src}")
    print(f"src_sha256={hashlib.sha256(original).hexdigest()}")
    print(f"out={args.out}")
    print(f"out_sha256={hashlib.sha256(rendered.encode()).hexdigest()}")
    print(f"stages_patched={patched}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
