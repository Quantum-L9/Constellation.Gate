# GATE_SDK_REQUIRED_DELTA

> **STATUS: SATISFIED — 2026-09-01. This document is now a historical record.**
>
> The requested capability shipped in Gate_SDK
> `bfe6642062a85a720ad8c25e96446d4df1c299ac` (PR #40) as
> `GateDispatchTransport.send_gate_authored_packet()`, and Constellation.Gate
> consumes it as of `3b5c959`. `routing/worker_transport.py` — the Gate-local
> adapter this request existed to remove — is deleted, and the
> shadow-transport allow-list is empty.
>
> Nothing below is an open request any more. It is retained because it records
> *why* the Gate-local adapter existed and what was required to retire it; a
> reader who finds a similar adapter later should be able to see how that gap
> was closed rather than re-derive it. Do not treat any "missing", "absent", or
> "blocked" statement in the rest of this file as current.
>
> Current state: `FINAL_FINDINGS.md` and `PR_FINDINGS_BRIEF.md`.

**Original status:** `BLOCKED_EXTERNAL_SDK_CAPABILITY` *(superseded)*
**Required capability:** `gate_authorized_worker_packet_transport` *(delivered)*
**Blocked ADR:** ADR-GATE-005 (Gate_SDK owns Gate→worker transport mechanics)
**Requesting repository:** `Quantum-L9/Constellation.Gate`
**Target repository:** `Quantum-L9/Gate_SDK`
**SDK state examined when written:** `d09fe58a6cd68ef8aa883896c68badc95f96e090`
**Delivered in:** `bfe6642062a85a720ad8c25e96446d4df1c299ac`
**Date raised:** 2026-08-31 · **Date satisfied:** 2026-09-01

---

## 1. Why this file exists

ADR-GATE-005 requires that after Gate makes the routing decision, **Gate_SDK owns
the mechanics of transporting the canonical packet**. Gate still owns *where* the
packet goes — routing is its authority, and it legitimately knows worker URLs.
What it must not own is a second implementation of canonical packet transport.

Gate currently performs that transport itself in
`routing/dispatch.py::_post_dispatch_packet`.

The ADR's stop rule says: if the SDK cannot express this safely, report the gap
and **do not conceal it with another Gate-local transport abstraction**. That is
what this file does. Gate's dispatcher was left as the single, guarded adapter
rather than being refactored into a new Gate-local abstraction that would look
like closure without being it.

## 2. The gap, precisely

Gate_SDK at `d09fe58` exposes exactly one outbound packet transport:

```python
GateClient.send_to_gate(packet) -> TransportPacket   # node -> Gate
```

Its own docstring states the constraint that makes it unusable here:

> "This client is the only allowed outbound inter-node transport surface.
> **It never accepts an arbitrary peer URL.**"

That constraint is correct and must not be relaxed — it is what prevents
node→node routing (ADR-GATE-001). But it means there is **no SDK primitive for
the one actor legitimately allowed to address a worker directly: Gate**.

Searched and confirmed absent at `d09fe58`:

| Searched for | Result |
|---|---|
| A Gate→worker transport primitive | absent |
| Any `send_to_worker` / `dispatch_to_node` equivalent | absent |
| Any transport entry point accepting a resolved target URL | absent |
| Worker-side ingress validators (`validate_execute_ingress_packet`) | **present** — Gate already consumes these |

So the worker *receiving* half of this contract is SDK-owned; only the Gate
*sending* half is missing.

## 3. Requested API (smallest sufficient shape)

```python
async def send_gate_authored_packet(
    packet: TransportPacket,      # already derived + hopped by Gate
    *,
    target_url: str,              # resolved by Gate's registry; Gate's authority
    timeout_seconds: float,       # remaining packet budget (ADR-GATE-008)
) -> TransportPacket:
    ...
```

The SDK would own, and Gate would delete:

- outbound canonical validation
- signing where configured
- packet serialization
- the `POST /v1/execute` call
- the actual network timeout
- HTTP status → typed failure classification
- response decoding
- response packet validation

Gate retains: target selection, deadline arithmetic, per-node concurrency,
registry health marking.

### Required guard

This must **not** become a general node-to-peer side door. Suggested shapes,
in preference order:

1. A separate module/namespace (e.g. `constellation_node_sdk.gate_authority`)
   documented as Gate-only, not exported from the node-facing `gate` package.
2. A required explicit caller assertion that `packet.provenance.origin_kind ==
   "gate"` and `resolved_by_gate is True`, raising otherwise — so a node cannot
   use it to reach a peer even by importing it.

Option 2 is mechanically enforceable and is what Gate would prefer.

### Typed failures Gate wants to consume

Gate currently flattens transport failures into `RuntimeError`, losing the
cause. It would consume, in preference to parsing `httpx`:

- worker unreachable / connection failure
- worker timeout (distinct from Gate's own deadline expiry)
- worker returned a non-2xx status
- worker returned a body that is not a canonical `TransportPacket`

## 4. What Gate has already done, so this is the only remaining item

The Gate-side work does not wait on this capability. Delivered in this pass:

- the transport call is isolated to one adapter method, guarded by an
  architecture test that fails if any second module learns to POST a canonical
  packet (`tests/architecture/test_architecture_drift_guards.py`);
- the deadline already flows into that call, so the SDK primitive can accept
  `timeout_seconds` with no further Gate change;
- the packet handed to it is already fully derived, hopped, and validated.

When the SDK primitive lands, the change on Gate's side is the body of
`_post_dispatch_packet` and the shrinking of `WORKER_TRANSPORT_ADAPTER` to
empty.

## 5. Two SDK defects found while proving this (already fixed upstream)

Running Gate's derived packet through the **real** SDK worker validators —
rather than Gate's own fixtures, which agreed with Gate — surfaced two defects
present at Gate's previous pin `a770e853`:

1. **`derive()` carried parent hops into the child.** The inherited hop kept the
   parent's `packet_id`, so `validate_hop_trace()` rejected it. Every Gate→worker
   dispatch would have failed at any SDK-based worker.
2. **`_canonicalize` used local-time datetimes**, making `transport_hash`
   machine-dependent (Mac EDT vs Docker UTC).

Both are already fixed in SDK `d09fe58`. Gate's pin has been advanced to that
commit and both fixes are now asserted by
`tests/architecture/test_sdk_transport_compatibility.py`.

**Recommendation for Gate_SDK:** the SDK's own test suite did not catch either
defect, because both are only observable when a *Gate-authored derived* packet
meets the *worker-side* validators. A round-trip fixture in the SDK covering
`root packet → derive → worker ingress validation` would close that class of
gap at its source.
