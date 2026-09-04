"""Real-process harness for the EIE <-> Gate <-> CEG seam.

Nothing here is a mock. Each node is the real repository checkout, launched
from its own virtualenv as a separate OS process, listening on a real TCP
port, and every packet crosses a real socket. The harness only knows how to
start, probe, stop, and read the logs of those processes, and how to run a
short driver script *inside* a peer's own interpreter (so that "EIE sends"
means EIE's code, in EIE's process, with EIE's dependencies).

Secrets (signing key, admin token) are generated per session, passed only via
process environment, and never written to the evidence file or the logs.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

GATE_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE = GATE_ROOT.parents[0] if GATE_ROOT.name == "constellation-gate" else GATE_ROOT.parent
if GATE_ROOT.name == "constellation-gate":
    WORKSPACE = GATE_ROOT.parent.parent


def _root(env_name: str, default_dirname: str) -> Path:
    raw = os.environ.get(env_name, "").strip()
    return Path(raw).expanduser().resolve() if raw else (WORKSPACE / default_dirname).resolve()


def _venv_python(root: Path) -> Path | None:
    candidate = root / ".venv" / "bin" / "python"
    return candidate if candidate.exists() else None


@dataclass(frozen=True)
class Peer:
    name: str
    root: Path
    python: Path
    port: int

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


@dataclass
class ManagedProcess:
    label: str
    cmd: list[str]
    cwd: Path
    env: dict[str, str]
    log_path: Path
    proc: subprocess.Popen[bytes] | None = None
    _log_fh: Any = field(default=None, repr=False)

    def start(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_fh = self.log_path.open("ab")
        self.proc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            self.cmd,
            cwd=str(self.cwd),
            env=self.env,
            stdout=self._log_fh,
            stderr=subprocess.STDOUT,
        )

    def wait_http(
        self, url: str, *, timeout: float = 90.0, ok: tuple[int, ...] = (200,)
    ) -> httpx.Response:
        deadline = time.monotonic() + timeout
        last: str = "no response"
        while time.monotonic() < deadline:
            if self.proc is not None and self.proc.poll() is not None:
                raise RuntimeError(
                    f"{self.label} exited with {self.proc.returncode} before becoming ready:\n{self.log_tail()}"
                )
            try:
                response = httpx.get(url, timeout=3.0)
                if response.status_code in ok:
                    return response
                last = f"HTTP {response.status_code}: {response.text[:300]}"
            except httpx.HTTPError as exc:
                last = f"{type(exc).__name__}: {exc}"
            time.sleep(0.5)
        raise RuntimeError(
            f"{self.label} not ready at {url} after {timeout}s ({last})\n{self.log_tail()}"
        )

    def stop(self, *, grace: float = 10.0) -> None:
        if self.proc is None:
            return
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=grace)
        if self._log_fh is not None:
            self._log_fh.close()
            self._log_fh = None

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def log_text(self) -> str:
        try:
            return self.log_path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return ""

    def log_tail(self, lines: int = 40) -> str:
        return "\n".join(self.log_text().splitlines()[-lines:])


class PeerDriverError(RuntimeError):
    pass


def run_in_peer(
    peer: Peer, code: str, env: dict[str, str], *, timeout: float = 120.0
) -> dict[str, Any]:
    """Run ``code`` inside the peer's own interpreter and return its JSON result.

    The driver must print exactly one JSON object as its last stdout line.
    """
    full_env = {**env, "PYTHONPATH": str(peer.root), "PYTHONUNBUFFERED": "1"}
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [str(peer.python), "-c", code],
        cwd=str(peer.root),
        env=full_env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if completed.returncode != 0 or not lines:
        raise PeerDriverError(
            f"driver in {peer.name} failed (rc={completed.returncode})\nSTDOUT:\n{completed.stdout[-2000:]}\nSTDERR:\n{completed.stderr[-4000:]}"
        )
    try:
        result = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise PeerDriverError(
            f"driver in {peer.name} printed non-JSON last line: {lines[-1][:500]}"
        ) from exc
    if not isinstance(result, dict):
        raise PeerDriverError(
            f"driver in {peer.name} must return a JSON object, got {type(result).__name__}"
        )
    result.setdefault("_stderr_tail", completed.stderr[-1500:])
    result.setdefault("_stdout_tail", completed.stdout[-3000:])
    return result


@dataclass
class SeamContext:
    gate_root: Path
    gate_python: Path
    eie: Peer
    ceg: Peer
    gate_port: int
    receipt_dir: Path
    signing_key: str = field(repr=False)
    admin_token: str = field(repr=False)
    neo4j_uri: str = "bolt://127.0.0.1:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = field(default="", repr=False)
    key_ids: dict[str, str] = field(
        default_factory=lambda: {"gate": "gate-e2e", "eie": "eie-e2e", "ceg": "ceg-e2e"}
    )

    @property
    def gate_url(self) -> str:
        return f"http://127.0.0.1:{self.gate_port}"

    def verifying_keys_json(self) -> str:
        return json.dumps({key_id: self.signing_key for key_id in self.key_ids.values()})

    def _base_env(self) -> dict[str, str]:
        # A minimal, explicit environment: nothing from the harness shell leaks
        # into the nodes except PATH/HOME/proxy plumbing needed to run at all.
        keep = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE")
        env = {name: os.environ[name] for name in keep if name in os.environ}
        env["NO_PROXY"] = "127.0.0.1,localhost"
        env["no_proxy"] = "127.0.0.1,localhost"
        env["PYTHONUNBUFFERED"] = "1"
        return env

    def gate_env(self) -> dict[str, str]:
        return {
            **self._base_env(),
            "L9_ENVIRONMENT": "local",
            "GATE_LOCAL_NODE": "gate",
            "HOST": "127.0.0.1",
            "PORT": str(self.gate_port),
            "L9_DEV_MODE": "false",
            "L9_REQUIRE_SIGNATURE": "true",
            "L9_SIGNING_ALGORITHM": "hmac-sha256",
            "L9_SIGNING_KEY": self.signing_key,
            "L9_SIGNING_KEY_ID": self.key_ids["gate"],
            "L9_VERIFYING_KEYS_JSON": self.verifying_keys_json(),
            "GATE_ADMIN_TOKEN": self.admin_token,
            "L9_REPLAY_ENABLED": "true",
        }

    def _node_env(self, owner: str, node_name: str) -> dict[str, str]:
        return {
            **self._base_env(),
            "GATE_URL": self.gate_url,
            "GATE_ADMIN_TOKEN": self.admin_token,
            "GATE_REGISTRATION_ENABLED": "true",
            "GATE_REGISTER_OVERWRITE": "true",
            "L9_ENVIRONMENT": "local",
            "L9_NODE_NAME": node_name,
            "L9_GATE_NODE_NAME": "gate",
            "L9_ENFORCE_GATE_ONLY_INGRESS": "true",
            "L9_REQUIRE_SIGNATURE": "true",
            "L9_SIGNING_ALGORITHM": "hmac-sha256",
            "L9_SIGNING_KEY": self.signing_key,
            "L9_SIGNING_KEY_ID": self.key_ids[owner],
            "L9_VERIFYING_KEYS_JSON": self.verifying_keys_json(),
            "L9_MAX_ATTACHMENTS": "0",
            "L9_MAX_ATTACHMENT_SIZE_BYTES": "0",
        }

    def eie_env(self) -> dict[str, str]:
        env = self._node_env("eie", "enrichment-engine")
        env.update(
            {
                "GATE_INTERNAL_URL": self.eie.url,
                "KB_DIR": str(self.eie.root / "kb"),
                "DOMAINS_DIR": str(self.eie.root / "domains"),
                "GRAPH_SYNC_ENTITY_TYPE": "facilities",
                "GRAPH_SYNC_ID_PROPERTY": "facility_id",
                "LOG_LEVEL": "INFO",
                # Deliberately no LLM provider credentials: the seam under test is
                # transport; provider availability is reported, not assumed.
                "PERPLEXITY_API_KEY": "",
            }
        )
        return env

    def ceg_env(self, spec_path: Path) -> dict[str, str]:
        env = self._node_env("ceg", "graph")
        env.update(
            {
                "L9_CHASSIS": "sdk",
                "L9_ENV": "dev",
                "L9_SERVICE_NAME": "graph-engine",
                "L9_SERVICE_VERSION": "1.1.0",
                "HOST": "127.0.0.1",
                "L9_NODE_SPEC_PATH": str(spec_path),
                "GATE_NODE_SPEC_PATH": str(spec_path),
                "L9_ALLOWED_ACTIONS": "match,sync,admin,outcomes,resolve,health,healthcheck",
                "NEO4J_URI": self.neo4j_uri,
                "NEO4J_USERNAME": self.neo4j_user,
                "NEO4J_PASSWORD": self.neo4j_password,
                "DOMAINS_ROOT": str(self.ceg.root / "domains"),
                "GDS_ENABLED": "false",
                "LOG_LEVEL": "info",
            }
        )
        return env


def build_context(receipt_dir: Path) -> SeamContext | None:
    """Resolve peers; return None (caller skips) when the cross-repo layout is absent."""
    eie_root = _root("L9_SEAM_EIE_ROOT", "Enrichment.Inference.Engine")
    ceg_root = _root("L9_SEAM_CEG_ROOT", "Cognitive.Engine.Graphs")
    gate_python = _venv_python(GATE_ROOT) or Path(sys.executable)
    eie_python = _venv_python(eie_root)
    ceg_python = _venv_python(ceg_root)
    if (
        not (eie_root / "app" / "main.py").exists()
        or not (ceg_root / "chassis" / "entrypoint.py").exists()
    ):
        return None
    if eie_python is None or ceg_python is None:
        return None
    base_port = int(os.environ.get("L9_SEAM_BASE_PORT", "19000"))
    return SeamContext(
        gate_root=GATE_ROOT,
        gate_python=gate_python,
        eie=Peer("eie", eie_root, eie_python, base_port + 1),
        ceg=Peer("ceg", ceg_root, ceg_python, base_port + 2),
        gate_port=base_port,
        receipt_dir=receipt_dir,
        signing_key=secrets.token_hex(32),
        admin_token=secrets.token_urlsafe(24),
        neo4j_uri=os.environ.get("L9_SEAM_NEO4J_URI", "bolt://127.0.0.1:7687"),
        neo4j_user=os.environ.get("L9_SEAM_NEO4J_USER", "neo4j"),
        neo4j_password=os.environ.get("L9_SEAM_NEO4J_PASSWORD", ""),
    )


class Evidence:
    """Append-only record of what each test observed; written as JSON at session end."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.entries: list[dict[str, Any]] = []
        self.meta: dict[str, Any] = {}

    def record(self, check_id: str, *, direction: str, status: str, **details: Any) -> None:
        self.entries.append(
            {
                "id": check_id,
                "direction": direction,
                "status": status,
                "observed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                **details,
            }
        )
        self.flush()

    def flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"meta": self.meta, "entries": self.entries}, indent=2, default=str)
        )


def count_matching(text: str, needle: str) -> int:
    return sum(1 for line in text.splitlines() if needle in line)
