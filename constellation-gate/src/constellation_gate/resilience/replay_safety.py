"""Explicit replay-safety contract for Gate-level whole-operation retry.

Gate dispatches an action to a worker over HTTP. A ``TimeoutError`` on that
call means "no answer arrived", not "no work happened" -- the worker may have
completed the operation and its side effects. Automatically re-running the
*whole* operation because the exception happened to be timeout-shaped is
therefore a correctness hazard, not resilience.

Two independent conditions must BOTH hold before Gate replays an operation:

1. the action is declared replay-safe by explicit operator contract, and
2. the packet carries a stable idempotency key.

An idempotency key alone is necessary but NOT sufficient: a key lets a *worker*
deduplicate, it does not prove the worker actually does. Declaring an action
replay-safe alone is not sufficient either: without a stable key there is
nothing for the worker to deduplicate on.

``converge`` is permanently denied. EIE owns provider retries for that action
(see the EIE convergence deadline contract); a Gate-level replay would stack a
second full provider waterfall on top of one that may already be running.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

from constellation_node_sdk.transport.packet import TransportPacket

# Actions that may never be replayed by Gate, regardless of configuration.
# Ownership of retry for these actions belongs to the worker, not the router.
NEVER_REPLAY_SAFE_ACTIONS: Final[frozenset[str]] = frozenset({"converge"})


class ReplaySafetyError(ValueError):
    """Raised when an action is declared replay-safe but must never be."""


class ReplaySafetyPolicy:
    """Decide whether a packet's operation may be replayed by Gate.

    Default posture: nothing is replay-safe. An operator opts an action in
    explicitly; there is no implicit global retry wrapper.
    """

    def __init__(self, replay_safe_actions: Iterable[str] = ()) -> None:
        normalized = {action.strip().lower() for action in replay_safe_actions if action.strip()}
        denied = normalized & NEVER_REPLAY_SAFE_ACTIONS
        if denied:
            raise ReplaySafetyError(
                f"actions {sorted(denied)!r} may never be declared Gate replay-safe; "
                "retry ownership for them belongs to the worker"
            )
        self._replay_safe_actions: frozenset[str] = frozenset(normalized)

    @property
    def replay_safe_actions(self) -> frozenset[str]:
        return self._replay_safe_actions

    def is_declared_replay_safe(self, action: str) -> bool:
        normalized = action.strip().lower()
        if normalized in NEVER_REPLAY_SAFE_ACTIONS:
            return False
        return normalized in self._replay_safe_actions

    def may_replay(self, packet: TransportPacket) -> bool:
        """Both conditions must hold: explicit safety contract AND stable key."""
        if not self.is_declared_replay_safe(packet.header.action):
            return False
        key = packet.header.idempotency_key
        return bool(key and str(key).strip())

    def attempts_for(self, packet: TransportPacket, *, max_attempts: int) -> int:
        """Attempt budget for this packet: ``max_attempts`` only when replay-safe."""
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        return max_attempts if self.may_replay(packet) else 1
