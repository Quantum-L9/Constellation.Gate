# Ingress Policy

## Purpose

Ingress policy defines what Gate will accept and what Gate must reject at the boundary.

This is where protocol correctness and routing law begin.

---

## Accepted traffic classes

### Client-origin packets
Allowed when:
- packet is valid
- destination is Gate
- request satisfies configured limits

### Node-origin reentry packets
Allowed when:
- `origin_kind == "node"`
- destination is Gate
- packet is valid and policy-compliant

### Gate-internal worker responses
Allowed through internal runtime flow after dispatch completion.

---

## Rejected traffic classes

### Direct node-to-node packets
Rejected because they bypass:
- Gate routing authority
- hop visibility
- lineage correctness

### Invalid packet shapes
Rejected when schema, size, timing, or packet-type constraints fail.

### Admission-rejected traffic
Rejected when:
- rate limit exceeded
- backpressure threshold exceeded
- load-shedding threshold exceeded
- circuit is open before execution

---

## Boundary checks

Ingress policy should validate:
- packet schema
- packet size
- allowed packet type
- timestamp skew
- hop depth
- delegation depth
- attachment count and size
- signature policy if enabled
- required idempotency policy for configured actions
- routing policy for origin/destination combination

---

## Routing-law checks

### Client path
```text
client -> gate
````

Allowed.

### Node reentry path

```text
node -> gate
```

Allowed.

### Peer bypass path

```text
node -> worker
```

Rejected.

---

## Fail-closed principle

Ingress policy must reject invalid or ambiguous traffic rather than silently repair authority state.

---

## Error mapping guidance

* invalid packet → `400`
* routing policy violation → `403`
* rate/backpressure/load shed → `429`
* circuit open / node saturation → `503`
* execution timeout → `504`

---

## Operator takeaway

Ingress policy is the first and strongest guardrail protecting the control plane.

