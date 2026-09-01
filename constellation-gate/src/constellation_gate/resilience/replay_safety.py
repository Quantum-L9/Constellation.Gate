"""Which actions Gate may replay as a whole operation (ADR-GATE-007).

Gate sits in front of side-effect-capable workers. Replaying a whole worker
operation because *some* exception was a ``TimeoutError`` is not a retry: a
timeout is the one failure mode where Gate cannot know whether the worker
already applied the effect. Multiplying the operation is therefore the least
safe response, not the most conservative one.

Automatic whole-operation replay requires BOTH:

1. a stable idempotency identity on the packet, and
2. an explicit declaration that the action is safe for Gate-level replay.

Idempotency alone is necessary but not sufficient -- a key makes a replay
*recognisable*, not *harmless*. The default for every action is one attempt.

``converge`` is deliberately absent: provider retry ownership belongs to EIE
(ADR-GATE-016). Gate must not independently multiply a converge operation.
"""

from __future__ import annotations

from typing import Final

# Actions explicitly proven safe for Gate-authored whole-operation replay.
# Empty by default: nothing is replay-safe until a contract says so and the
# claim is backed by an executable test.
GATE_REPLAY_SAFE_ACTIONS: Final[frozenset[str]] = frozenset()

# Actions whose retry ownership is explicitly delegated to the worker/domain
# authority. Listed for documentation and for the drift guard -- promoting any
# of these into GATE_REPLAY_SAFE_ACTIONS is an architecture change.
WORKER_OWNED_RETRY_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        "converge",
        "graph-inference-result",
        "match",
        "sync",
        "outcomes",
    }
)

# Gate-level whole-operation attempts for an action with no explicit contract.
DEFAULT_MAX_ATTEMPTS: Final[int] = 1

# Attempts granted to an action that IS declared replay-safe and carries a
# stable idempotency key.
REPLAY_SAFE_MAX_ATTEMPTS: Final[int] = 3


def normalize_action(action: str) -> str:
    return action.strip().lower()


def is_declared_replay_safe(action: str) -> bool:
    """True only when the action is explicitly declared safe for Gate replay."""
    return normalize_action(action) in GATE_REPLAY_SAFE_ACTIONS


def max_attempts_for(*, action: str, has_idempotency_key: bool) -> int:
    """Resolve the whole-operation attempt budget for one packet.

    Fails closed to a single attempt unless the action is declared replay-safe
    AND the packet carries a stable idempotency identity.
    """
    if not is_declared_replay_safe(action):
        return DEFAULT_MAX_ATTEMPTS
    if not has_idempotency_key:
        return DEFAULT_MAX_ATTEMPTS
    return REPLAY_SAFE_MAX_ATTEMPTS
