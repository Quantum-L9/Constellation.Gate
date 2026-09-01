"""Static drift guards over Gate production code (ADR-GATE-017).

These read the source tree rather than exercising behaviour: they exist to fail
a review the moment Gate starts growing a second implementation of something it
does not own -- domain semantics, or canonical packet transport.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "constellation_gate"

# Empty, and it stays empty. Gate_SDK bfe6642 shipped the Gate-authorized worker
# transport primitive this allow-list was waiting for, so the Gate-local adapter
# collapsed into GateDispatchTransport.send_gate_authored_packet() and was
# deleted. No production module may speak canonical worker HTTP again: the
# ratchet reached zero and only shrinks.
WORKER_TRANSPORT_ADAPTER: set[str] = set()

# Modules legitimately holding an HTTP client for non-worker-dispatch reasons.
HTTP_INFRASTRUCTURE = {"runtime/http_client.py", "routing/health_monitor.py"}

# Application/domain vocabulary Gate must never interpret (ADR-GATE-003).
FORBIDDEN_DOMAIN_TOKENS = (
    "entity_snapshot",
    "enrichrequest",
    "enrichresponse",
    "final_fields",
    "writeback",
)


def _production_files() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts)


def _rel(path: Path) -> str:
    return path.relative_to(SRC).as_posix()


def _imports_httpx(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] == "httpx" for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] == "httpx":
                return True
    return False


def _has_outbound_post(path: Path) -> bool:
    """True when a module performs any outbound HTTP POST of its own.

    Path-agnostic on purpose. ``_has_outbound_execute_post`` below keys on the
    canonical ``/v1/execute`` string, which a re-implementation could simply
    spell differently; this one cannot be dodged that way.
    """
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    if not _imports_httpx(tree):
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Await):
            call = node.value
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "post"
            ):
                return True
    return False


def _has_outbound_execute_post(path: Path) -> bool:
    """True when a module makes an outbound canonical-packet POST.

    Distinguishes an OUTBOUND client call (``await client.post(...)``) from
    Gate's own INBOUND route declaration (``@app.post("/v1/execute")``), which
    is Gate's ingress and entirely legitimate. Matching on the ``/v1/execute``
    string alone conflates the two.
    """
    text = path.read_text(encoding="utf-8")
    if "/v1/execute" not in text:
        return False

    tree = ast.parse(text)
    if not _imports_httpx(tree):
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.Await):
            call = node.value
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "post"
            ):
                return True
    return False


@pytest.mark.parametrize("path", _production_files(), ids=_rel)
def test_no_domain_vocabulary_in_production_code(path: Path) -> None:
    """Gate must not acquire a vocabulary for the domains it routes."""
    text = path.read_text(encoding="utf-8").lower()
    found = [token for token in FORBIDDEN_DOMAIN_TOKENS if token in text]
    assert not found, f"{_rel(path)} references domain vocabulary {found}; Gate payloads are opaque"


def test_worker_dispatch_http_stays_in_the_single_transport_adapter() -> None:
    """Guard the seam: no second place may learn to POST a canonical packet.

    Gate legitimately KNOWS worker URLs -- routing is its authority. What it must
    not do is grow a second implementation of canonical packet transport after
    the routing decision is made.
    """
    offenders = []
    for path in _production_files():
        rel = _rel(path)
        if rel in WORKER_TRANSPORT_ADAPTER or rel in HTTP_INFRASTRUCTURE:
            continue
        if _has_outbound_execute_post(path):
            offenders.append(rel)

    assert not offenders, (
        f"{offenders} perform worker-packet HTTP outside the single transport adapter "
        f"{sorted(WORKER_TRANSPORT_ADAPTER)}"
    )


def test_transport_adapter_surface_is_empty() -> None:
    """The adapter list is a ratchet: it reached zero and may never grow."""
    assert WORKER_TRANSPORT_ADAPTER == set()


def test_no_gate_local_worker_transport_module_exists() -> None:
    """The Gate-local adapter is gone, not merely unused."""
    assert not (SRC / "routing" / "worker_transport.py").exists(), (
        "routing/worker_transport.py reappeared; the Gate->worker hop belongs to "
        "GateDispatchTransport.send_gate_authored_packet()"
    )


def test_dispatcher_delegates_transport_and_owns_no_http() -> None:
    """Dispatcher decides WHERE; it must not reacquire HOW."""
    source = (SRC / "routing" / "dispatch.py").read_text(encoding="utf-8")
    assert "send_gate_authored_packet" in source, (
        "dispatcher must route through the SDK's Gate-authorized transport"
    )
    assert "raise_for_status" not in source, "HTTP status mapping belongs to the SDK"
    assert ".json()" not in source, "response decoding belongs to the SDK"
    assert "model_validate" not in source, "response packet validation belongs to the SDK"
    assert "client.post" not in source, "the dispatcher must perform no HTTP of its own"


def test_no_module_both_posts_and_revives_a_canonical_packet() -> None:
    """Catch a worker transport re-implementation spelled at a different path.

    The outbound guard keys on the literal ``/v1/execute``; a reimplementation
    could use a different string and slip past it. The pairing cannot be dodged:
    performing an outbound POST *and* reviving a canonical packet from a body is
    what canonical transport IS, whatever the URL says.

    Deliberately NOT a blanket ban on ``TransportPacket.model_validate``. Gate
    legitimately revives packets it did not receive over a worker socket --
    ``boundary/transport_codec.py`` decodes Gate's own INBOUND ingress body, and
    ``services/execute_service.py`` revives a packet from Gate's idempotency
    cache. Banning the call outright would flag both and teach the next reader
    that ingress decoding is drift, which it is not.
    """
    offenders = []
    for path in _production_files():
        rel = _rel(path)
        if rel in HTTP_INFRASTRUCTURE:
            continue
        text = path.read_text(encoding="utf-8")
        if "TransportPacket.model_validate" in text and _has_outbound_post(path):
            offenders.append(rel)
    assert not offenders, (
        f"{offenders} both POST and revive a canonical packet; that pairing is "
        "worker transport, which belongs to Gate_SDK"
    )


def test_retry_policy_default_is_a_single_attempt() -> None:
    """A generic wrapper must never default to replaying side-effectful work."""
    from constellation_gate.resilience.retry_policy import RetryPolicy

    assert RetryPolicy().max_attempts == 1


def test_execute_service_does_not_cache_on_the_raw_idempotency_key() -> None:
    """Guard against a regression to the cross-tenant-collidable cache key."""
    source = (SRC / "services" / "execute_service.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "set":
            continue
        if isinstance(func.value, ast.Attribute) and func.value.attr == "idempotency_store":
            raise AssertionError(
                "execute_service calls idempotency_store.set(...) directly; "
                "use set_for_packet(...) so the key stays tenant/action namespaced"
            )


def test_replay_guard_expires_inside_check_and_record() -> None:
    """The declared window must be enforced on the hot path, not by prune()."""
    source = (SRC / "resilience" / "replay_guard.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    check = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "check_and_record"
    )
    calls = {
        node.func.attr
        for node in ast.walk(check)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "_expire" in calls, "check_and_record must expire entries itself"
