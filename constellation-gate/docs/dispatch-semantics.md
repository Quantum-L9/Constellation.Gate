# Dispatch Semantics

## Purpose

Dispatch is the step where Gate turns a valid Gate-bound intent packet into a worker-targeted execution packet.

This is the point where routing authority becomes concrete.

---

## Dispatch Law

Only Gate may emit worker-targeted dispatch packets.

A valid dispatch packet must satisfy:
- `address.source_node == gate`
- `address.destination_node == <worker>`
- `provenance.origin_kind == "gate"`
- `provenance.resolved_by_gate == true`

---

## Dispatch Flow

```text
ingress packet (destination=gate)
  -> ingress hop
  -> resolve target
  -> derive worker-targeted packet
  -> dispatch hop
  -> POST /v1/execute on worker
  -> validate worker response
````

---

## Derivation Rules

Dispatch must derive a new packet, not mutate the ingress packet.

Expected changes:

* new `packet_id`
* `lineage.parent_id = ingress.packet_id`
* same `lineage.root_id`
* incremented `lineage.generation`
* `source_node = gate`
* `destination_node = worker`
* `reply_to = gate`

---

## Hop semantics

### Ingress hop

Recorded when Gate accepts and validates ingress intent.

### Dispatch hop

Recorded when Gate authors worker dispatch.

These hops provide:

* semantic traceability
* routing visibility
* lineage reconstruction

---

## Concurrency and safety

Dispatch should respect:

* per-node concurrency ceilings
* worker health status
* timeout budgets
* admission control

---

## Failure semantics

### Transport failure

If worker call fails at transport level:

* mark worker unhealthy when appropriate
* fail request
* preserve audit/logging signal

### Execution failure

If worker returns a failure packet or Gate execution fails terminally:

* surface failure coherently
* dead-letter if configured at execution layer

---

## Invariants

1. Gate dispatch is explicit, never implicit.
2. Gate dispatch must be derived, never in-place.
3. Gate dispatch is the only legal path from intent to worker execution.
4. Dispatch packets preserve lineage and append observable hops.

