# Workflow Engine

## Purpose

The workflow engine executes compound actions declaratively inside Gate.

It exists to let Gate compose multi-node work without giving routing authority to nodes.

---

## Conceptual model

A workflow is:
- named by action
- declared as ordered steps
- executed within Gate
- dispatched one step at a time through Gate routing

---

## Example

```yaml
workflows:
  full_pipeline:
    description: "Enrich then score"
    steps:
      - action: enrich
        payload_transform: merge_payload
      - action: score
        payload_transform: merge_results
````

Request:

```text
action=full_pipeline
destination=gate
```

Execution:

```text
gate -> enrich step -> gate
gate -> score step -> gate
gate -> final response
```

---

## Step model

Each step may contain:

* `action`
* `timeout_ms`
* `payload_transform`
* `condition`
* `target_node`

Gate still owns target resolution and policy checks.

---

## Condition evaluation

Conditions decide whether a step runs.

Requirements:

* deterministic
* side-effect free
* safe evaluation only
* based on current workflow state/payload

---

## Payload transform strategies

### `identity`

Pass current payload unchanged.

### `merge_payload`

Merge current payload with previous result.

### `merge_results`

Accumulate prior result fields into workflow state.

---

## Failure model

Default model:

* any terminal step failure terminates workflow
* Gate emits coherent failure outcome
* failed workflow may be dead-lettered by execution policy

---

## Why the workflow engine belongs in Gate

If nodes orchestrate peers directly:

* routing authority fragments
* lineage visibility degrades
* debugging gets harder
* location-agnosticity is lost

Keeping workflow decomposition inside Gate preserves the control-plane model.

---

## Invariants

1. Workflow requests enter Gate as one action.
2. Each step becomes its own Gate-mediated dispatch.
3. Worker nodes remain pure execution units.
4. Workflow composition is visible and auditable.

