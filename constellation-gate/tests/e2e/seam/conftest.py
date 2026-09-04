"""Session fixtures: one real Gate, one real EIE, one real CEG, all as separate processes."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from .harness import GATE_ROOT, Evidence, ManagedProcess, SeamContext, build_context

_RECEIPT_ROOT = Path(
    os.environ.get("L9_SEAM_RECEIPT_DIR", str(GATE_ROOT / ".l9" / "runtime" / "seam-e2e"))
)


@pytest.fixture(scope="session")
def receipt_dir() -> Path:
    path = _RECEIPT_ROOT / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture(scope="session")
def ctx(receipt_dir: Path) -> SeamContext:
    context = build_context(receipt_dir)
    if context is None:
        pytest.skip(
            "cross-repo seam E2E needs sibling checkouts of Enrichment.Inference.Engine and "
            "Cognitive.Engine.Graphs (or L9_SEAM_EIE_ROOT / L9_SEAM_CEG_ROOT) each with a .venv; "
            "not present on this runner"
        )
    return context


@pytest.fixture(scope="session")
def evidence(ctx: SeamContext) -> Iterator[Evidence]:
    ev = Evidence(ctx.receipt_dir / "seam_evidence.json")
    ev.meta = {
        "gate_root": str(ctx.gate_root),
        "eie_root": str(ctx.eie.root),
        "ceg_root": str(ctx.ceg.root),
        "gate_url": ctx.gate_url,
        "eie_url": ctx.eie.url,
        "ceg_url": ctx.ceg.url,
        "neo4j_uri": ctx.neo4j_uri,
        "signature_required": True,
        "signing_algorithm": "hmac-sha256",
        "key_ids": ctx.key_ids,
        "secrets_in_receipt": False,
    }
    ev.flush()
    yield ev
    ev.flush()


@pytest.fixture(scope="session")
def gate(ctx: SeamContext, evidence: Evidence) -> Iterator[ManagedProcess]:
    proc = ManagedProcess(
        label="constellation-gate",
        cmd=[
            str(ctx.gate_python),
            "-m",
            "uvicorn",
            "constellation_gate.api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(ctx.gate_port),
        ],
        cwd=ctx.gate_root,
        env=ctx.gate_env(),
        log_path=ctx.receipt_dir / "gate.log",
    )
    proc.start()
    health = proc.wait_http(f"{ctx.gate_url}/v1/health").json()
    evidence.meta["gate_health"] = health
    evidence.meta["gate_pid"] = proc.proc.pid if proc.proc else None
    yield proc
    proc.stop()


@pytest.fixture(scope="session")
def eie(ctx: SeamContext, gate: ManagedProcess, evidence: Evidence) -> Iterator[ManagedProcess]:
    proc = ManagedProcess(
        label="enrichment-inference-engine",
        cmd=[
            str(ctx.eie.python),
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(ctx.eie.port),
        ],
        cwd=ctx.eie.root,
        env=ctx.eie_env(),
        log_path=ctx.receipt_dir / "eie.log",
    )
    proc.start()
    proc.wait_http(f"{ctx.eie.url}/api/v1/health", ok=(200, 503))
    evidence.meta["eie_pid"] = proc.proc.pid if proc.proc else None
    yield proc
    proc.stop()


@pytest.fixture(scope="session")
def ceg_spec_path(ctx: SeamContext) -> Path:
    """The repo's engine/spec.yaml with internal_url pointed at this session's port."""
    original = (ctx.ceg.root / "engine" / "spec.yaml").read_text(encoding="utf-8")
    rewritten = "\n".join(
        (f'  internal_url: "{ctx.ceg.url}"' if line.strip().startswith("internal_url:") else line)
        for line in original.splitlines()
    )
    assert rewritten != original, "engine/spec.yaml has no internal_url line to rewrite"
    path = ctx.receipt_dir / "ceg_spec.e2e.yaml"
    path.write_text(rewritten + "\n", encoding="utf-8")
    return path


@pytest.fixture(scope="session")
def ceg(
    ctx: SeamContext, gate: ManagedProcess, ceg_spec_path: Path, evidence: Evidence
) -> Iterator[ManagedProcess]:
    proc = ManagedProcess(
        label="cognitive-engine-graphs",
        cmd=[
            str(ctx.ceg.python),
            "-m",
            "uvicorn",
            "chassis.entrypoint:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(ctx.ceg.port),
        ],
        cwd=ctx.ceg.root,
        env=ctx.ceg_env(ceg_spec_path),
        log_path=ctx.receipt_dir / "ceg.log",
    )
    proc.start()
    proc.wait_http(f"{ctx.ceg.url}/v1/health", ok=(200, 503))
    evidence.meta["ceg_pid"] = proc.proc.pid if proc.proc else None
    yield proc
    proc.stop()


@pytest.fixture(scope="session")
def constellation(
    ctx: SeamContext,
    gate: ManagedProcess,
    eie: ManagedProcess,
    ceg: ManagedProcess,
    evidence: Evidence,
) -> dict:
    """All three processes up and both nodes visible in Gate's live registry."""
    deadline = time.monotonic() + 60
    snapshot: dict = {}
    while time.monotonic() < deadline:
        snapshot = httpx.get(f"{ctx.gate_url}/v1/registry", timeout=5.0).json()
        if "enrichment-engine" in snapshot and "graph" in snapshot:
            break
        time.sleep(1.0)
    evidence.meta["registry_snapshot"] = snapshot
    (ctx.receipt_dir / "registry_snapshot.json").write_text(
        json.dumps(snapshot, indent=2, default=str)
    )
    return snapshot
