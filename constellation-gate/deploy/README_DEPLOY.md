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
L9_ENVIRONMENT=production
GATE_LOCAL_NODE=gate
HOST=0.0.0.0
PORT=9000
L9_GATE_ADMIN_TOKEN=<token>
```

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

