# Node registration (Gate admin API)

## Purpose

Worker and orchestrator nodes **register** with Gate so Gate can resolve `action` → healthy node instances. This document describes the **payload shape** produced by `constellation_node_sdk.gate.registration.build_registration_payload()` and sent to Gate.

## Endpoint (Gate)

```text
POST {GATE_URL}/v1/admin/register?overwrite=true|false
Content-Type: application/json
X-Admin-Token: <optional; from env when Gate requires it>
```

Gate validates the body and returns success or rejection; the SDK treats non-2xx as registration failure (startup may still continue depending on config).

## Wire payload shape

Top-level object: **keys are node ids** (lowercase). Each value describes one node:

| Field | Required | Meaning |
|-------|----------|---------|
| `internal_url` | Yes | Absolute base URL for Gate→node dispatch (e.g. `http://score:8000`). |
| `supported_actions` | Yes | Non-empty list of action strings Gate may route here. |
| `priority_class` | No | Default `P2`; values like `P0`–`P3`. |
| `max_concurrent` | No | Default `50`. |
| `health_endpoint` | No | Default `/v1/health`. |
| `timeout_ms` | No | Default `30000`. |
| `metadata` | No | Includes `version`, `type`, `generated_by: constellation-node-sdk`. |

### Example JSON

```json
{
  "score": {
    "internal_url": "http://score:8000",
    "supported_actions": ["score"],
    "priority_class": "P1",
    "max_concurrent": 25,
    "health_endpoint": "/v1/health",
    "timeout_ms": 15000,
    "metadata": {
      "version": "1.2.3",
      "type": "worker",
      "generated_by": "constellation-node-sdk"
    }
  }
}
```

## SDK source (`spec.yaml`)

Registration is built from a YAML spec (path from `GATE_NODE_SPEC_PATH`, default `engine/spec.yaml`):

- **`node.id`** — required; becomes the top-level key.
- **`node.actions`** — required non-empty list; becomes `supported_actions`.
- **`node.internal_url`** — optional; default `http://{id}:8000`.
- Optional: `priority_class`, `max_concurrent`, `health_endpoint`, `timeout_ms`, `version`, `type`.

See `src/constellation_node_sdk/gate/registration.py` for the exact mapping.

## Rules

- Node ids and actions are normalized to **lowercase**.
- `internal_url` must be usable by Gate for HTTP dispatch (absolute URL).
- `overwrite=false` may cause **409** if the node already exists (Gate-defined).

Gate remains authoritative for **health**, **activation**, and **registry** state after registration.
