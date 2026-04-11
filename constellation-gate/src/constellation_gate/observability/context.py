from __future__ import annotations

from contextvars import ContextVar
from typing import Any

_GATE_CONTEXT: ContextVar[dict[str, Any]] = ContextVar("_GATE_CONTEXT", default={})


def get_context() -> dict[str, Any]:
    return dict(_GATE_CONTEXT.get())


def set_context(**values: Any) -> None:
    current = dict(_GATE_CONTEXT.get())
    current.update(values)
    _GATE_CONTEXT.set(current)


def clear_context() -> None:
    _GATE_CONTEXT.set({})
