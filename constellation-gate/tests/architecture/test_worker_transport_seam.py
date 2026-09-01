"""Exactly one module owns Gate->worker packet transport mechanics.

Gate may know worker URLs -- it is the routing authority, that is its job. What
it may not do is grow a second place that independently serializes a canonical
packet, POSTs it to a worker's /v1/execute, and decodes the reply. Every such
place is another spot where the deadline, the error taxonomy, and (once the SDK
ships the primitive) the migration have to be repeated, and repeated correctly.

This test holds that boundary now, and keeps holding it after the SDK migration:
when `worker_transport.post_worker_packet` becomes a thin call into an SDK
primitive, the allow-list does not change.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "constellation_gate"

# The single sanctioned Gate->worker packet-transport adapter.
WORKER_TRANSPORT_ADAPTER = "routing/worker_transport.py"

# Health probing is a liveness GET, not packet transport: it carries no
# TransportPacket and answers a different question. It is allowed its own client.
HEALTH_PROBE_MODULE = "routing/health_monitor.py"

# Owns the pooled AsyncClient lifecycle; constructs a client but sends nothing.
CLIENT_LIFECYCLE_MODULE = "runtime/http_client.py"

ALLOWED_HTTP_SENDER_MODULES = frozenset(
    {WORKER_TRANSPORT_ADAPTER, HEALTH_PROBE_MODULE, CLIENT_LIFECYCLE_MODULE}
)

WORKER_EXECUTE_PATH = "/v1/execute"


def _modules() -> list[Path]:
    return sorted(p for p in SRC_ROOT.rglob("*.py") if "egg-info" not in str(p))


def _rel(path: Path) -> str:
    return path.relative_to(SRC_ROOT).as_posix()


# Modules permitted to mention the worker execute path at all:
#   routing/dispatch.py       -- builds the target URL (a routing decision)
#   routing/worker_transport.py -- documents the seam it owns
#   api/main.py               -- SERVES Gate's own ingress; opposite direction
EXPECTED_EXECUTE_PATH_MODULES = frozenset(
    {"routing/dispatch.py", "routing/worker_transport.py", "api/main.py"}
)


def test_worker_execute_path_stays_inside_the_routing_seam() -> None:
    """No module outside the routing seam may name the worker execute path."""
    referencing = {
        _rel(module)
        for module in _modules()
        if WORKER_EXECUTE_PATH in module.read_text(encoding="utf-8")
    }

    unexpected = referencing - EXPECTED_EXECUTE_PATH_MODULES
    assert not unexpected, (
        f"modules outside the routing seam reference {WORKER_EXECUTE_PATH!r}: "
        f"{sorted(unexpected)}. Outbound worker transport belongs behind "
        f"{WORKER_TRANSPORT_ADAPTER}; inbound ingress belongs in api/main.py."
    )


def test_only_the_transport_seam_sends_http() -> None:
    """No module outside the allow-list may issue an HTTP request."""
    offenders: list[str] = []

    for module in _modules():
        rel = _rel(module)
        if rel in ALLOWED_HTTP_SENDER_MODULES:
            continue
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in {
                "post",
                "get",
                "put",
                "patch",
                "delete",
                "request",
                "send",
            }:
                # Narrow to calls on something that looks like an HTTP client,
                # so ordinary dict/registry `.get(...)` is not swept up.
                target = func.value
                target_name = ""
                if isinstance(target, ast.Name):
                    target_name = target.id
                elif isinstance(target, ast.Attribute):
                    target_name = target.attr
                elif isinstance(target, ast.Call):
                    target_name = ast.unparse(target)
                if "client" in target_name.lower() or "httpx" in target_name.lower():
                    offenders.append(f"{rel}:{node.lineno}: {ast.unparse(func)}")

    assert not offenders, (
        "HTTP is issued outside the sanctioned transport seam:\n  "
        + "\n  ".join(offenders)
        + f"\nMove it behind {WORKER_TRANSPORT_ADAPTER}."
    )


def test_dispatcher_delegates_transport_and_owns_no_http_call() -> None:
    """Dispatcher decides WHERE; it must not implement HOW."""
    source = (SRC_ROOT / "routing" / "dispatch.py").read_text(encoding="utf-8")
    assert "post_worker_packet" in source, "dispatcher must route through the transport seam"
    assert "raise_for_status" not in source, "HTTP status mapping belongs to the transport seam"
    assert ".json()" not in source, "response decoding belongs to the transport seam"


def test_transport_seam_documents_the_sdk_migration() -> None:
    """The seam must say why it is Gate-local, so it is not mistaken for a design."""
    source = (SRC_ROOT / "routing" / "worker_transport.py").read_text(encoding="utf-8")
    assert "GATE_SDK_REQUIRED_DELTA.md" in source, (
        "the transport seam exists only because the SDK lacks a Gate-authorized "
        "worker-transport primitive; it must point at the required delta"
    )
