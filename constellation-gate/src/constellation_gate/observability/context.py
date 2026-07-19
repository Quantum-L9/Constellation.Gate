from __future__ import annotations

from contextvars import ContextVar
from typing import Any

_GATE_CONTEXT: ContextVar[dict[str, Any] | None] = ContextVar("_GATE_CONTEXT", default=None)


def get_context() -> dict[str, Any]:
    current = _GATE_CONTEXT.get()
    return dict(current) if current else {}


def set_context(**values: Any) -> None:
    current = _GATE_CONTEXT.get()
    updated = dict(current) if current else {}
    updated.update(values)
    _GATE_CONTEXT.set(updated)


def clear_context() -> None:
    _GATE_CONTEXT.set({})
