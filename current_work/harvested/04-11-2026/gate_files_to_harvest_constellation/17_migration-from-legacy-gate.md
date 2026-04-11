# Migration from Legacy Gate

## Purpose

This document explains the shift from older Gate patterns to the current `TransportPacket`-first, Gate-authoritative model.

---

## Legacy patterns to remove

### 1. Alternate request envelopes
Old systems often accepted multiple request shapes.

Replace with:
- one canonical `TransportPacket`

### 2. Node-aware peer URLs
Old systems let nodes know other node URLs.

Replace with:
- `GATE_URL` only

### 3. Direct orchestrator-to-worker calls
Old systems treated orchestrators like internal routers.

Replace with:
- orchestrator -> Gate -> worker

### 4. Weak lineage semantics
Old systems often lost visibility after the first hop.

Replace with:
- Gate reentry and append-only hop history

---

## Migration steps

### Step 1 — canonicalize ingress
All execute paths should accept only `TransportPacket`.

### Step 2 — remove peer URL config
Nodes should keep exactly one outbound integration target:
```text
GATE_URL
````

### Step 3 — move routing into Gate

Any action-to-node or URL selection logic in workers/orchestrators must be deleted.

### Step 4 — derive responses and dispatches immutably

No in-place packet mutation.

### Step 5 — enforce architecture in tests

Add and keep:

* no direct node-to-node tests
* Gate dispatch authority tests
* lineage reentry tests

---

## What improves after migration

* stronger routing authority
* better auditability
* full lineage continuity
* cleaner orchestration model
* simpler node deployment and scaling

---

## Common migration mistakes

### Mistake: treating Gate as just a reverse proxy

Gate is a control-plane node, not a dumb HTTP relay.

### Mistake: keeping node destination URLs around “just in case”

That preserves architectural escape hatches and undermines the model.

### Mistake: hiding workflow steps inside nodes

Workflow state may live in Gate execution, but routing still belongs to Gate.

---

## End state

The correct end state is:

```text
one authoritative Gate
many private nodes
all inter-node work returns through Gate
```

