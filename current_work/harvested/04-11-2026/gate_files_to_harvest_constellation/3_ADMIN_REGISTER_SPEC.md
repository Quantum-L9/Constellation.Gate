# Admin Register Spec

## Purpose

`POST /v1/admin/register` is the only Gate-controlled mutation surface for updating the executable node registry.

This endpoint exists to:
- register internal worker/orchestrator nodes
- update node action coverage
- update runtime metadata such as timeout and concurrency ceilings
- preserve Gate as the sole routing authority

It is not a public endpoint.

---

## Endpoint

```text
POST /v1/admin/register
````

Headers:

* `X-Admin-Token: <token>` when admin auth is enabled

Query params:

* `overwrite=true|false`
  Defaults to `true`

---

## Request Contract

Content type:

```text
application/json
```

Canonical body shape:

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
      "domain": "matching",
      "version": "1.0.0"
    }
  },
  "enrich": {
    "internal_url": "http://enrich:8000",
    "supported_actions": ["enrich"],
    "priority_class": "P2",
    "max_concurrent": 20,
    "health_endpoint": "/v1/health",
    "timeout_ms": 30000,
    "metadata": {
      "domain": "research"
    }
  }
}
```

---

## Semantics

### 1. Gate remains authoritative

Registration only updates Gate’s registry view. It does not grant nodes peer-routing rights.

### 2. Actions are declarative

`supported_actions` tells Gate which node can legally receive a routed dispatch for a given action.

### 3. Node URLs are internal-only

`internal_url` is for Gate-to-node dispatch. Clients and peer nodes never use it directly.

### 4. Overwrite semantics

* `overwrite=true` means an existing registration may be replaced
* `overwrite=false` means duplicate node names should fail

---

## Field Definitions

### `internal_url`

* required
* must be `http://` or `https://`
* trailing slash is normalized away

### `supported_actions`

* required
* non-empty list
* values normalized to lowercase
* duplicates forbidden

### `priority_class`

* optional
* one of `P0`, `P1`, `P2`, `P3`
* used for operator visibility and future queueing policy

### `max_concurrent`

* optional
* integer ≥ 1
* used by Gate per-node concurrency protection

### `health_endpoint`

* optional
* default `/v1/health`
* path only

### `timeout_ms`

* optional
* integer ≥ 1
* upper bound for node dispatch timeout budget

### `metadata`

* optional
* free-form string map for operator/runtime annotations

---

## Response Contract

Canonical success shape:

```json
{
  "registered": [
    {
      "node_name": "score",
      "healthy": true,
      "registered": true
    },
    {
      "node_name": "enrich",
      "healthy": true,
      "registered": true
    }
  ],
  "total_nodes": 2
}
```

---

## Error Contract

### 400 Bad Request

Returned when request schema is invalid.

Example:

```json
{
  "detail": {
    "code": "invalid_request",
    "message": "supported_actions must not be empty"
  }
}
```

### 401 Unauthorized

Returned when admin auth is enabled and token is missing or invalid.

Example:

```json
{
  "detail": {
    "code": "admin_auth_failed",
    "message": "invalid admin token"
  }
}
```

### 409 Conflict

Recommended for future explicit duplicate registration conflicts when `overwrite=false`.

### 500 Internal Server Error

Returned for unexpected failures. Internal details must not leak.

---

## Invariants

1. Registration never grants direct node-to-node routing.
2. Gate remains the only authority that resolves action → node.
3. Registry state must remain deterministic and auditable.
4. Health starts as `healthy=true` on successful registration and is later updated by health monitoring.

