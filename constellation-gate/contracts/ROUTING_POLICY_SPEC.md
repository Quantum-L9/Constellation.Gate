# Routing policy (Constellation)

## Core rule

**All node-originated follow-up traffic must go through Gate** (`GATE_URL`). Nodes do not call other workers by URL.

## Allowed traffic patterns

| Pattern | Meaning |
|---------|---------|
| Client → Gate | Initial ingress. |
| Node → Gate | Follow-up work from a worker/orchestrator (destination Gate). |
| Gate → worker | Gate dispatch after policy + registry resolution. |

## Forbidden

- **Node A → Node B** directly (no peer HTTP between workers for Constellation routing).
- Embedding **peer node URLs** in node runtime config for Constellation dispatch (only `GATE_URL` for outbound).

## Packet semantics (policy-relevant)

**Node-origin follow-up** (orchestrator/worker sending the next hop):

- `provenance.origin_kind == "node"`
- `address.source_node` — the local node
- `address.destination_node` — **`gate`** for SDK-enforced outbound (see `gate/policy.py` + Gate client)

**Gate dispatch** (after Gate resolution):

- `provenance.origin_kind == "gate"`
- `provenance.resolved_by_gate == true`
- `address.source_node` — typically `gate`
- `address.destination_node` — resolved worker (Gate-defined)

## Enforcement layers

1. **SDK** — `GateClient`, `validate_outbound_gate_packet` / policy helpers (`src/constellation_node_sdk/gate/policy.py`).
2. **constellation-gate** — ingress validator, routing policy, dispatcher.

SDK and Gate must stay aligned; contract drift here breaks the security model.
