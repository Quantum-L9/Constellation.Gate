# TransportPacket specification

## Overview

`TransportPacket` is the **only** supported wire shape for Constellation node traffic carried by this SDK. Runtime and Gate client code validate **Pydantic** models (`src/constellation_node_sdk/transport/`).

`contracts/transport-packet.schema.json` is a **JSON Schema** view of the same object. The runtime adds **stricter** cross-field rules than JSON Schema alone (e.g. signature pairing, dispatch hops requiring `target_node`, failed hops requiring errors).

## Invariants

- **Canonical transport** — one model; no alternate envelopes in core paths.
- **Semantic change** — new logical work uses `derive()` (new `packet_id`, lineage, refreshed hashes).
- **Observational change** — routing/execution visibility uses `with_hop()`; **does not** change `transport_hash`.
- **Gate-only egress from nodes** — see `ROUTING_POLICY_SPEC.md`.

## Hashing (matches `transport/hashing.py`)

**`payload_hash`** — SHA-256 of canonical JSON of `payload` (`compute_payload_hash`).

**`transport_hash`** — SHA-256 of canonical JSON of a fixed envelope **excluding** `hop_trace` and **excluding** transport `signature` fields:

- `header`
- `address`
- `tenant`
- `payload`
- `governance`
- `delegation_chain`
- `lineage`
- `attachments`
- `provenance`
- `payload_hash` (the `security.payload_hash` string)

`hop_trace` is never part of this envelope.

## Enumerations (runtime)

| Field | Allowed values |
|-------|----------------|
| `header.packet_type` | `request`, `response`, `event`, `command`, `delegation`, `failure`, `replay_request`, `replay_response`, `compensation` |
| `header.action` | Lowercase: `[a-z0-9][a-z0-9-]{0,63}` |
| `security.classification` | `public`, `internal`, `confidential`, `restricted` |
| `security.encryption_status` | `plaintext`, `encrypted`, `envelope_only` |
| `security.signature_algorithm` | `hmac-sha256`, `ed25519` (if signature present) |
| `provenance.origin_kind` | `client`, `node`, `gate` |
| Hop `direction` | `ingress`, `dispatch`, `execution`, `response` |
| Hop `status` | `received`, `validated`, `processing`, `delegated`, `completed`, `failed` |

## Signatures

- **Transport** — signs `transport_hash` (when signing is enabled); `signature` and `signature_algorithm` must both be set or both absent.
- **Hop** (optional) — signs hop record; `hop_signature` / `hop_signature_algorithm` / `hop_signing_key_id` rules mirror transport on `TransportHop`.

## Lineage

- Root: `lineage.parent_id == null`, `generation == 0`, `root_id == header.packet_id` (by convention at creation).
- Child from `derive()`: new `packet_id`, `parent_id` → parent, same `root_id`, `generation` incremented.

## Related files

- Schema: `transport-packet.schema.json`
- Models: `transport/models.py`, `transport/packet.py`, `transport/provenance.py`, `transport/tenant.py`
- Hashing: `transport/hashing.py`
