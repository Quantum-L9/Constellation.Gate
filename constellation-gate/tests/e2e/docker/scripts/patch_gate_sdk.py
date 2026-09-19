#!/usr/bin/env python3
"""Point Gate's rendered Dockerfile at the vendored SDK export.

Gate's requirements.lock installs the SDK from a GitHub *archive tarball* URL
under `pip --require-hashes`. This session's egress proxy serves anonymous git
reads of public GitHub repositories but returns HTTP 403 for
github.com/.../archive/*.tar.gz, so that one requirement cannot be fetched.

This rewrites exactly one RUN instruction so the SDK is installed from the
`l9sdk` build context (a `git archive` export of the SAME commit the lock
pins -- see vendor_gate_sdk.sh). Every other requirement keeps
--require-hashes. The repository Dockerfile is not modified on disk.

Fails loudly if the anchor is absent: a silently unpatched Dockerfile would
produce an image that does not match what this harness claims to test.
"""

from __future__ import annotations

import sys
from pathlib import Path

ANCHOR = (
    "RUN python -m pip install --require-hashes --no-deps -r requirements.lock \\\n"
    "    && useradd --create-home --uid 10001 gate"
)

REPLACEMENT = (
    "# --- l9-e2e SDK vendoring (patch_gate_sdk.py): the GitHub archive URL in\n"
    "# requirements.lock is not fetchable here. The SDK is installed from the\n"
    "# exact commit that lock pins, exported over git. Every other requirement\n"
    "# keeps --require-hashes.\n"
    "COPY --from=l9sdk / /opt/gate_sdk\n"
    "RUN grep -v 'Gate_SDK/archive' requirements.lock > /tmp/requirements.nosdk.lock \\\n"
    "    && python -m pip install --require-hashes --no-deps -r /tmp/requirements.nosdk.lock \\\n"
    "    && python -m pip install --no-deps /opt/gate_sdk \\\n"
    "    && useradd --create-home --uid 10001 gate"
)


def main() -> int:
    path = Path(sys.argv[1])
    text = path.read_text(encoding="utf-8")
    if ANCHOR not in text:
        print(
            f"FATAL: install anchor not found in {path}.\n"
            "Gate's Dockerfile changed; update patch_gate_sdk.py rather than "
            "shipping an unpatched build.",
            file=sys.stderr,
        )
        return 1
    path.write_text(text.replace(ANCHOR, REPLACEMENT), encoding="utf-8")
    print(f"patched {path}: SDK installed from vendored l9sdk context")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
