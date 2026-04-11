# Action Resolution

## Purpose

Gate resolves an incoming `TransportPacket` to the correct internal node.

This is a control-plane decision, not a client or node concern.

---

## Inputs

Resolution uses:
- `packet.header.action`
- `packet.address.destination_node`
- Gate-local node name
- current registry state
- node health state
- supported action index

---

## Resolution Rules

### Rule 1 — Gate-bound packets resolve by action
If the packet targets Gate itself:

```text
destination_node == gate
````

Gate resolves:

```text
action -> candidate nodes -> chosen node
```

### Rule 2 — Gate-authored worker dispatch resolves by explicit destination

If the packet is already a Gate-authored dispatch:

* `provenance.origin_kind == "gate"`
* `provenance.resolved_by_gate == true`

then Gate validates the explicit destination node instead of re-resolving by action.

### Rule 3 — Node-origin peer-targeted packets are not routable

If a node-origin packet targets a worker directly, that is a policy violation, not a valid routing input.

---

## Determinism Requirements

1. Resolution must be stable for a given registry snapshot.
2. Registry lookup is a Gate concern only.
3. Worker selection must not bypass health and capacity protections.

---

## Registry Inputs

Each node registration contributes:

* `node_name`
* `internal_url`
* `supported_actions`
* `healthy`
* `active_requests`
* `max_concurrent`
* `timeout_ms`

---

## Recommended Selection Policy

For a given action:

1. filter nodes supporting the action
2. filter healthy nodes
3. prefer least-loaded node
4. break ties deterministically by node name

This keeps routing:

* observable
* auditable
* reproducible enough for debugging

---

## Failure Modes

### Unknown action

No node advertises the action.

### No healthy nodes

Action exists, but all candidates are unhealthy.

### Invalid explicit destination

A Gate-authored dispatch references a node that is absent or unhealthy.

These must fail closed.

---

## What resolution is not

Resolution is not:

* a client-side decision
* a node-side service discovery concern
* a hidden workflow side effect

It is a Gate-owned routing operation.

