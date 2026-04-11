# Workflow Spec

## Purpose

Gate workflows define **compound actions** that Gate decomposes into multiple internally routed `TransportPacket` steps.

A workflow is not peer choreography.

It is:
- requested through Gate
- decomposed by Gate
- dispatched step-by-step by Gate
- fully visible in lineage and hop history

---

## Core Routing Law

Allowed:
```text
client -> gate -> workflow engine -> gate -> worker
```

Forbidden:

```text
orchestrator -> worker
workflow step -> peer node directly
```

Every step returns to Gate routing authority.

---

## Workflow Model

A workflow is keyed by action name.

Example:

```yaml
workflows:
  full_pipeline:
    description: "Enrich then score an entity"
    steps:
      - action: enrich
        payload_transform: merge_payload
      - action: score
        payload_transform: merge_results
```

---

## Schema

### Top-level

```yaml
workflows:
  <workflow_name>:
    description: <string>
    steps:
      - action: <string>
        timeout_ms: <int|null>
        payload_transform: identity|merge_payload|merge_results
        condition: <string|null>
        target_node: <string|null>
```

### Step fields

#### `action`

Required.
The action Gate routes for that step.

#### `timeout_ms`

Optional per-step timeout override.

#### `payload_transform`

How Gate prepares the next step payload:

* `identity` — pass current payload unchanged
* `merge_payload` — merge prior payload with prior step result
* `merge_results` — accumulate prior step outputs into current payload

#### `condition`

Optional boolean expression controlling whether a step runs.

#### `target_node`

Optional explicit destination hint. Gate still validates and owns dispatch.

---

## Execution Semantics

### Step execution

For each step:

1. Gate derives a child `TransportPacket`
2. destination is `gate`, not the worker directly
3. Gate resolves action or explicit target
4. Gate dispatches as a Gate-authored worker-targeted packet
5. response returns to Gate
6. Gate updates workflow state
7. next step begins

### Lineage

* root packet retains root lineage
* each step increments generation
* each dispatch appends ingress/dispatch hops
* full chain remains reconstructible

### Failure behavior

* step failure terminates workflow unless future compensating semantics are introduced
* terminal failures should be visible in Gate logs/metrics and may be dead-lettered by execution policy

---

## Determinism Requirements

1. Step order is explicit.
2. Conditional evaluation must be deterministic for a given state.
3. Payload transforms must be stable and documented.
4. Gate is the only component allowed to decide the actual dispatch target.

---

## Recommended Response Shape

Workflow execution returns a canonical `TransportPacket` response whose payload contains:

* final aggregated workflow result
* step outputs if retained
* status

Example payload:

```json
{
  "status": "completed",
  "workflow": "full_pipeline",
  "entity_id": "42",
  "industry": "fintech",
  "score": 91
}
```

---

## Invariants

1. Workflow steps never bypass Gate.
2. Workflow definitions are declarative, not imperative peer-call scripts.
3. Gate remains sole routing authority even when `target_node` is provided.
4. Workflow state is internal to Gate execution, not distributed implicitly across nodes.

