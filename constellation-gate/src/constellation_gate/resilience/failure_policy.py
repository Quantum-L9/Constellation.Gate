from __future__ import annotations


class FailurePolicy:
    def classify(self, exc: Exception) -> str:
        if isinstance(exc, TimeoutError):
            return "timeout"
        if isinstance(exc, ValueError):
            return "validation"
        return "internal"

    def should_retry(self, category: str) -> bool:
        return category in {"timeout", "internal"}
