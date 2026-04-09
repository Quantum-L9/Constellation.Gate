from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ExecutionState:
    packet_id: str
    status: str
    attempts: int = 0
