# Changelog

All notable changes to `constellation-gate` are documented here.

The format follows Keep a Changelog and semantic versioning.

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
