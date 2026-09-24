#!/usr/bin/env python3
"""Fail-closed source provenance for the Docker E2E rail.

A release-set PASS is only evidence if the images were built from — and the
run was bound to — exact, clean source revisions. Recording ``git status`` is
not enough: a dirty worktree still builds, and the recorded head then names a
commit the image does not contain. This module turns provenance into an input
contract that build_images.sh and run_e2e.sh both enforce BEFORE doing work.

Subcommands
-----------
sources   Every repository in the release set must be a clean checkout (no
          modified, staged or untracked-but-unignored files — the Docker
          build context would include them). When ``L9_E2E_EXPECT_<NODE>_SHA``
          is set, HEAD must equal it. Writes a JSON receipt; exits 1 on any
          violation, having still written the receipt so the failure is
          inspectable.
sdk-lock  Print the one Gate_SDK commit Gate's requirements.lock resolves to.
          Zero or several SDK requirements, or one that is not a 40-hex
          archive commit, is a failure: there is no fallback SDK.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# node -> (repository directory under the workspace, expected-sha env var)
RELEASE_SET: dict[str, tuple[str, str]] = {
    "gate": ("Constellation.Gate", "L9_E2E_EXPECT_GATE_SHA"),
    "eie": ("Enrichment.Inference.Engine", "L9_E2E_EXPECT_EIE_SHA"),
    "ceg": ("Cognitive.Engine.Graphs", "L9_E2E_EXPECT_CEG_SHA"),
}

SDK_REQ = re.compile(r"^constellation-node-sdk\s*@\s*(?P<url>\S+)")
ARCHIVE_SHA = re.compile(r"/Gate_SDK/archive/(?P<sha>[0-9a-f]{40})\.tar\.gz$")
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


def _git(repo: Path, *args: str) -> tuple[int, str]:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode, completed.stdout.strip()


def source_state(repo: Path, expected: str | None) -> dict[str, object]:
    """Judge one checkout. Returns a record with ``violations`` (empty = ok)."""
    violations: list[str] = []
    code, head = _git(repo, "rev-parse", "--verify", "HEAD")
    if code != 0 or not FULL_SHA.match(head):
        return {"path": str(repo), "head": None, "violations": ["not a git checkout"]}
    _, branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    # --porcelain lists modified, staged AND untracked files but not ignored
    # ones: exactly the set that can change what a Docker build context holds.
    code, status = _git(repo, "status", "--porcelain")
    if code != 0:
        violations.append("git status failed")
    dirty = status.splitlines() if status else []
    if dirty:
        violations.append(f"dirty worktree ({len(dirty)} paths)")
    if expected is not None:
        if not FULL_SHA.match(expected):
            violations.append(f"expected sha {expected!r} is not a 40-hex commit")
        elif head != expected:
            violations.append(f"HEAD {head} is not the expected {expected}")
    return {
        "path": str(repo),
        "head": head,
        "branch": branch,
        "expected": expected,
        "dirty_paths": dirty,
        "violations": violations,
    }


def check_sources(workspace: Path, env: dict[str, str]) -> dict[str, object]:
    nodes: dict[str, object] = {}
    for node, (directory, env_var) in RELEASE_SET.items():
        nodes[node] = {"repo": directory, **source_state(workspace / directory, env.get(env_var))}
    ok = all(not rec["violations"] for rec in nodes.values() if isinstance(rec, dict))
    return {"verdict": "PASS" if ok else "FAIL", "nodes": nodes}


def sdk_lock_sha(lock_text: str) -> str:
    """Return the single Gate_SDK archive commit in a requirements.lock."""
    urls = [m["url"] for line in lock_text.splitlines() if (m := SDK_REQ.match(line.strip()))]
    if len(urls) != 1:
        msg = f"expected exactly one constellation-node-sdk requirement, found {len(urls)}"
        raise ValueError(msg)
    match = ARCHIVE_SHA.search(urls[0])
    if match is None:
        msg = f"constellation-node-sdk is not a Gate_SDK archive commit URL: {urls[0]!r}"
        raise ValueError(msg)
    return match["sha"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    src = sub.add_parser("sources")
    src.add_argument("--workspace", type=Path, required=True)
    src.add_argument("--out", type=Path, required=True)
    lock = sub.add_parser("sdk-lock")
    lock.add_argument("lock", type=Path)
    args = parser.parse_args(argv)

    if args.command == "sources":
        receipt = check_sources(args.workspace, dict(os.environ))
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(receipt, indent=1) + "\n")
        for node, rec in receipt["nodes"].items():  # type: ignore[union-attr]
            state = "; ".join(rec["violations"]) or "clean"
            print(f"source {node}: {rec.get('head')} [{state}]")
        if receipt["verdict"] != "PASS":
            print("FATAL: release-set sources are not clean/expected revisions", file=sys.stderr)
            return 1
        return 0

    try:
        print(sdk_lock_sha(args.lock.read_text()))
    except (OSError, ValueError) as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
