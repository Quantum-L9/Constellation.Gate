# Gate Kernel

## Purpose

The Gate kernel is the control-plane heart of the constellation.

It is responsible for:
- ingress validation
- routing policy
- action resolution
- workflow orchestration
- worker dispatch
- registry authority

---

## What Gate owns

### 1. Ingress boundary
Gate is the only accepted ingress point for:
- clients
- node reentry
- workflow continuation

### 2. Routing authority
Gate decides where work goes.  
Nodes do not.

### 3. Workflow composition
Compound actions are decomposed and executed inside Gate.

### 4. Dispatch visibility
Every worker dispatch is visible to Gate and represented in lineage/hops.

---

## What Gate does not own

Gate does not own:
- worker domain logic
- peer node discovery in nodes
- arbitrary public multi-route APIs
- node-local business semantics

---

## Kernel layers

### Boundary
Ingress decoding, validation, routing-law enforcement.

### Routing
Registry, resolver, dispatcher, health monitor, priority queue.

### Orchestration
Workflow definitions, step execution, conditions, payload aggregation.

### Services
Execute path, admin registration, registry query.

### Runtime
Lifecycle, shared async client, node concurrency protection, health/metrics surface.

---

## Kernel execution paths

### Atomic path
```text
request -> validate -> resolve -> dispatch -> worker response
````

### Workflow path

```text
request -> validate -> workflow engine
        -> step dispatch
        -> step dispatch
        -> final response
```

---

## Operator mental model

Gate is not just an API façade.

It is:

* the source of routing truth
* the boundary for policy
* the semantic trace anchor
* the execution coordinator

---

## Design invariant

If Gate did not see the hop, the system should treat that hop as non-canonical.

