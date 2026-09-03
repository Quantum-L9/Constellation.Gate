# Changelog

All notable changes to `constellation-gate` are documented here.

The format follows Keep a Changelog and semantic versioning.

## [1.1.0] - 2026-09-02

Repairs from the IB-Odoo_19 -> Gate_SDK -> Constellation.Gate -> EIE seam audit.

### Added
- `Dockerfile` (+ `.dockerignore`) installing from a pinned `requirements.lock`;
  `deploy/docker-compose.yml` now carries a build context. Previously the
  compose file named an image nothing could build.
- Worker health re-probe loop (`HealthMonitor`) started in the ASGI lifespan,
  cadence `GATE_HEALTH_PROBE_INTERVAL_SECONDS`. A worker marked unhealthy on a
  connection failure is restored to routing when its health endpoint answers
  again; before this the mark was permanent until re-registration or restart.
- Static registry load from `GATE_NODE_REGISTRY_PATH` at startup; the shipped
  `config/node_registry.yaml` is now in the loader's shape and pre-declares the
  canonical enrichment worker.
- `GATE_IDEMPOTENCY_TTL_SECONDS`: the routing-level idempotency cache expires
  entries instead of holding them for the life of the process.
- `GATE_RESPONSE_MARGIN_MS`: Gate reserves a slice of each packet's budget so a
  worker timeout surfaces as Gate's 504 before the caller's socket deadline.
- JSON logging configured at startup; `X-Request-ID` request context bound to
  every packet log line.

### Changed
- A routed action whose owner is unhealthy answers 503 `no_healthy_node`
  instead of 404 `not_found`; only an action Gate does not route is a 404.
  Callers classify 404 as permanent, so a worker blip looked like a
  missing route.
- `/v1/execute` re-signs the response under Gate's own key when Gate signs.
  It previously relayed the worker's packet with the worker's signature, so a
  caller in a signed topology had to hold every worker's verifying key.
- A signing key is validated at startup: `L9_SIGNING_KEY` needs
  `L9_SIGNING_KEY_ID`, and `L9_SIGNING_ALGORITHM` defaults to `hmac-sha256`.
  Previously the incoherent pair started cleanly and every dispatch failed
  with a 500 (`GateDispatchConfigurationError`).
- `GATE_ADMIN_TOKEN` is required in `staging` and `prod`; startup fails closed
  because an unauthenticated `/v1/admin/register` is routing takeover.
- Default `PORT` is 9000, matching every shipped deployment asset.
- Terraform `allowed_cidrs` has no world-open default and refuses `0.0.0.0/0`.
- Deployment docs name the canonical `GATE_ADMIN_TOKEN` variable.

## [1.0.0] - 2026-04-09

### Added
- Canonical `TransportPacket` ingress and dispatch path.
- Gate-only routing authority enforcement.
- Node registry, resolver, dispatcher, workflow engine, and admin registration flows.
- Async single-Gate hardening:
  - shared HTTP client lifecycle
  - per-node concurrency protection
  - admission control
  - timeout, retry, replay, idempotency, and dead-letter capture
- Structured observability:
  - metrics
  - tracing helpers
  - event/log context generation
- Architecture and integration coverage for:
  - no direct node-to-node routing
  - Gate-authored dispatch
  - lineage reentry
  - workflow execution via Gate
- Deployment assets:
  - docker compose
  - Prometheus alert rules
  - Terraform scaffold
- Contracts and operator documentation for:
  - admin registration
  - workflow definitions
  - ingress policy
  - dispatch semantics
  - migration from legacy Gate patterns

### Fixed
- Single-Gate async lifecycle now initializes shared outbound HTTP client before execution.
- Dispatch concurrency protection now releases node permits deterministically in `finally`.
- API error mapping now aligns admission failures, node saturation, timeouts, and routing errors to stable HTTP responses.

### Notes
- Shared state remains intentionally process-local in this version:
  - registry
  - replay state
  - idempotency cache
  - dead-letter queue
- This release is production-credible for a single authoritative Gate and is the correct baseline for future Gate 2.5 replicated-Gate work.
