# Gate Deployment Guide

This directory contains the **operator-facing deployment assets** for `constellation-gate`.

The target operating model for this version is:

```text
one authoritative async Gate
many internal nodes behind it
all inter-node work re-enters through Gate
````

---

## What is here

* `docker-compose.yml` — local and single-host runtime composition
* `prometheus.rules.yml` — baseline alerting for Gate health, failures, and admission pressure
* `terraform/` — infrastructure scaffold for cloud provisioning

---

## Deployment modes

### 1. Local development

Use Docker Compose.

```bash
docker compose -f deploy/docker-compose.yml up --build
```

### 2. Single-host production-like validation

Use:

* built Gate image
* external reverse proxy or direct exposure
* Prometheus scraping enabled
* internal worker nodes reachable on private network

### 3. Cloud bootstrap

Use Terraform to provision:

* host(s)
* network ingress
* instance bootstrap
* DNS / outputs

---

## Required environment variables

At minimum:

```text
L9_ENVIRONMENT=prod
GATE_LOCAL_NODE=gate
HOST=0.0.0.0
PORT=9000
GATE_ADMIN_TOKEN=<token>          # required in staging/prod; startup refuses to run without it
```

`L9_GATE_ADMIN_TOKEN` is still read as a backward-compatible alias.

Routing and resilience tuning (all optional, defaults shown):

```text
GATE_NODE_REGISTRY_PATH=          # static worker registry YAML, loaded at startup
GATE_HEALTH_PROBE_INTERVAL_SECONDS=15
GATE_IDEMPOTENCY_TTL_SECONDS=86400
GATE_RESPONSE_MARGIN_MS=500
```

The image is built from the repository `Dockerfile`; `docker compose -f
deploy/docker-compose.yml up --build` builds and runs it. In `staging`/`prod`
one ingress trust boundary must also be declared (`L9_REQUIRE_SIGNATURE=true`
with `L9_VERIFYING_KEYS_JSON`, or `L9_TRUSTED_INGRESS_BOUNDARY=network` with
evidence) or startup fails; see `.env.example`.

Consumers (callers that only send work, e.g. Odoo) do not register with Gate.
They are admitted by adding their key id to `L9_VERIFYING_KEYS_JSON` and a
caller policy record in `L9_KEY_ALLOWED_ACTIONS_JSON`. Each record binds the
verified key to one node, one kind (`consumer` or `worker`), the tenants it
may name, and the actions it may invoke:

```text
L9_KEY_ALLOWED_ACTIONS_JSON={"odoo-e2e":{"node":"odoo","kind":"consumer","tenants":["plasticos"],"actions":["converge","match"]}}
```

`odoo-e2e` may call `converge` and `match`. `sync`, a different `source_node`,
or a tenant outside that list is `403 action_not_permitted`. In `staging` and
`prod`, every id in `L9_VERIFYING_KEYS_JSON` must have a record or startup
fails; a verified key with no record is not a full participant. Local and dev
may boot with an empty map. A record for a key id that is not in
`L9_VERIFYING_KEYS_JSON` fails startup. Policies require
`L9_REQUIRE_SIGNATURE=true` (startup fails otherwise), and an unsigned packet
is refused while any policy is in force.

`GET /v1/registry` requires `X-Admin-Token`. The header is compared with
`hmac.compare_digest` against `GATE_ADMIN_TOKEN`. A missing or wrong token
returns `401` and no worker `internal_url`.

A consumer confirms its admission with `POST /v1/admission` (the Gate SDK's
`GateClient.activate()` does this): a signed probe with the reserved action
`gate.admission`, validated exactly like an execute request and never
dispatched. Gate answers with a Gate-signed response packet whose payload
(`l9.gate.admission.v1`) names the proven key id, whether the key is
`restricted` or `unrestricted`, and the actions it may invoke right now (its
scope intersected with the registered actions). An unknown key or a bad
signature gets `400`, an unsigned probe `403`. `gate.admission` can be neither
executed nor registered by a node.

Strongly recommended:

```text
L9_REQUIRE_SIGNATURE=true
L9_REPLAY_ENABLED=true
L9_VERIFY_HOP_SIGNATURES=true
```

---

## Deployment checklist

### Predeploy

```bash
python scripts/predeploy_check.py
pytest -q
ruff check src tests
mypy src
```

### Startup checks

* `/v1/health` returns healthy
* `/metrics` exports Prometheus metrics
* registry contains expected nodes after registration
* Gate can dispatch to internal nodes
* alert rules load in Prometheus

### Production checks

* admin token configured
* internal node URLs are private-only
* TLS terminated upstream
* Prometheus scraping active
* logs aggregated centrally

---

## Operational warnings

### Single-Gate scope

This release is production-credible for a **single Gate instance**. Shared state is still process-local:

* registry
* idempotency
* replay tracking
* dead-letter queue

### Future replicated-Gate work

Do not run multiple Gate replicas behind a load balancer until shared state is externalized consistently.

---

## Upgrade path

1. deploy single Gate
2. validate async pressure and worker dispatch
3. externalize shared state
4. then evaluate replicated Gate rollout

---

## Rollback

* revert image tag
* keep registry config under version control
* re-run startup checks
* verify `/v1/health` and `/metrics`
