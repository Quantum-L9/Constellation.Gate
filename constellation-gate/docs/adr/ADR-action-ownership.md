# ADR: Gate action ownership authority

## Status
Accepted for TASK-012

## Context
PlasticOS actions have a single semantic owner (TASK-002). Gate's NodeRegistry
is the topology authority for registration and workflow step dispatch. Without
ownership checks, a worker could advertise a canonical action belonging to
another service, and workflow configuration could drift onto a private action
index.

## Decision
1. Canonical actions `match`, `sync`, `outcomes` are owned by `ceg`.
2. Canonical actions `converge`, `graph-inference-result` are owned by `eie`.
3. Registration fails closed on owner mismatch or cross-owner collisions.
4. Same-owner replicas remain allowed for availability.
5. WorkflowEngine validates step actions against the same NodeRegistry instance
   used by AdminRegistrationService (`get_registry()` singleton).

## Consequences
- Conflicting ownership is rejected at registration time.
- Non-canonical actions retain multi-replica least-loaded routing.
- Capability sanitization remains TASK-013.
