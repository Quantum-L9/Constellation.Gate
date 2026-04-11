# Contracts

Normative interface definitions for Gate and for cross-repo alignment with **constellation-node-sdk**.

## Files

| File | Role | Source of truth |
|------|------|-----------------|
| `transport-packet.schema.json` | JSON Schema for `TransportPacket` (wire / validation). | **constellation-node-sdk** — keep in lockstep via sync script. |
| `TRANSPORT_PACKET_SPEC.md` | Human-readable TransportPacket contract (fields, invariants). | **constellation-node-sdk** |
| `NODE_REGISTRATION_SPEC.md` | Node registration record shape and semantics for the registry. | **constellation-node-sdk** |
| `ROUTING_POLICY_SPEC.md` | Routing policy / gate authority rules (documentation). | **constellation-node-sdk** |
| `WORKFLOW_SPEC.md` | Gate-only: compound workflows, steps, routing law for workflow execution. | **constellation-gate** (Gate product contract) |
| `ADMIN_REGISTER_SPEC.md` | Gate-only: `POST /v1/admin/register` request/response and semantics. | **constellation-gate** |

The first four files are **shared** with the SDK; the last two are **Gate-specific** APIs and behavior.

## Completeness (this repo)

Under `Gate/`, the only JSON Schema for packets is `transport-packet.schema.json`. All `*SPEC.md` contract documents for TransportPacket, registration, and routing policy live here and in `constellation-node-sdk/contracts/` at the repo root (same content for the shared set).

Example JSON payloads for manual testing live under **constellation-node-sdk** (`examples/packets/`); they are not duplicated in this folder.

## Sync shared contracts from the SDK

From the `constellation-gate` package root:

```bash
SDK_REPO_PATH="../constellation-node-sdk" sh scripts/sync_contracts_from_sdk.sh
```

This copies the four SDK-owned files into `contracts/`. It does **not** overwrite `WORKFLOW_SPEC.md` or `ADMIN_REGISTER_SPEC.md`.

Default in `sync_contracts_from_sdk.sh` is `../constellation-node-sdk` when run from `constellation-gate/` inside this monorepo.

## Validation

- `transport-packet.schema.json` must parse as JSON (`python3 -m json.tool contracts/transport-packet.schema.json`).
- Optional: run the SDK’s `scripts/validate_contracts.py` inside **constellation-node-sdk** (it checks schema + example packets against that package layout).
