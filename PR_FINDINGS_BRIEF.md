CONSTELLATION.GATE PR FINDINGS BRIEF

REPOSITORY:
  branch: claude/gate-routing-sdk-integration-tk6i2p
  candidate_head_sha: 342434b6ee0ceb8313550acc3d6d41a31dba1de6

MAKE PR:
  role: validation_gate
  result: PASS
  failed_phase_if_any: none
  note: |
    `make pr` did not exist; the Makefile was broken outright (trailing markdown
    junk -> "Makefile:33: *** missing separator") so lint/typecheck/test all
    failed to run at all. Repaired, then added `pr: lint typecheck contracts test`.
    It runs validation only. It does not push, publish, or open a remote PR.
    Required the sanctioned L4 sequence first (l4_local.py begin ->
    authorize-release), since the governance gate denies `make pr` mid-execution.

REMOTE PR:
  created: false
  number: null
  url: null
  base: main
  remote_head_sha: 342434b6ee0ceb8313550acc3d6d41a31dba1de6
  note: |
    Branch pushed to origin. No pull request was opened -- the execution contract
    did not request one. Open at:
    https://github.com/Quantum-L9/Constellation.Gate/pull/new/claude/gate-routing-sdk-integration-tk6i2p

VERDICT:
  routing: GO
  transport: BLOCKED_EXTERNAL_SDK_CAPABILITY
  domain_opacity: GO
  action_ownership: GO
  retry: GO
  deadline: GO
  idempotency: GO
  replay: GO
  ingress_security: FAIL_CLOSED_ENFORCED / boundary UNPROVEN from repo evidence
  gate_sdk: CONVERGED (a770e853 -> d09fe58)
  eie_routability: PASS (SDK-validating fixture) / live EIE NOT_RUN
  local: GO
  merge: APPROVE
  release_set: PENDING

IMPLEMENTED:
  - Repaired the Makefile (every make-based gate was dead) and added a `pr` target
  - Converged the Gate_SDK pin to d09fe58 (fixes derive() hop inheritance)
  - PacketDeadline: one monotonic budget reaching the real network client
  - ReplaySafetyPolicy: retry requires explicit safety contract AND a stable key
  - Idempotency namespaced by (tenant.org_id, action, key)
  - ReplayGuard: hot-path expiry + hard entry ceiling + injectable clock
  - GateSettings: staging/prod fail closed without a named ingress trust boundary
  - routing/worker_transport.py: single Gate->worker seam with typed errors
  - Wired the pooled client and per-node limiter that were built and never used
  - GET /v1/ready routability probe, distinct from /v1/health liveness
  - Worker transport failures map to 502 (504 on timeout), not 500
  - Bounded the dead-letter queue; corrected its durability docstring
  - Architecture guards: domain opacity (AST + adversarial) and transport seam
  - GATE_SDK_REQUIRED_DELTA.md and FINAL_FINDINGS.md

PROVEN:
  - Payload identity (value AND payload_hash) through ingress -> hop -> derive ->
    the packet actually handed to transport, over 6 adversarial payloads
  - The dispatched child passes the SDK's own validate_transport_packet
  - Full lineage/causation/hop/tenant contract on the converge round trip
  - Worker receives min(remaining, node cap): 28s spent of 30s -> worker gets 2.0s
  - No worker call at all once the budget is exhausted
  - Three dispatches under one deadline: 20.0 -> 12.0 -> 4.0
  - converge dispatches exactly once; cannot be configured replay-safe
  - Tenant A's cached response is never returned to tenant B
  - A packet_id is accepted again after the replay window elapses
  - 1000 unique packets stay bounded under a 100-entry ceiling
  - prod/staging refuse to start with no ingress trust boundary
  - The domain-opacity scan fails against a planted violation (negative control)

BLOCKERS:
  - none in Gate

NON_BLOCKING:
  - FailurePolicy is dead code that classifies TimeoutError as retryable,
    contradicting Gate's posture; a future caller would reopen the retry hole
  - config/node_registry.yaml ships stale legacy node entries
  - config/workflows.yaml full_pipeline references a non-canonical enrich node
  - deploy/docker-compose.yml uses .env.example as its env_file

GATE_SDK:
  exact_sha: d09fe58a6cd68ef8aa883896c68badc95f96e090
  previous_sha: a770e8531dc1c59ce01e1dbb0f4162785d9dda89
  worker_transport_sdk_owned: false
  external_capability_gap: |
    No Gate-authorized worker transport primitive. GateClient is structurally
    node->Gate: assert_node_origin_packet requires origin_kind=="node" (a Gate
    dispatch packet is "gate") and assert_gate_only_destination requires
    destination_node=="gate" (a dispatch packet targets a worker). Exact required
    API in GATE_SDK_REQUIRED_DELTA.md section 2.
  sdk_candidate_artifacts: |
    SDK branch claude/gate-routing-sdk-integration-tk6i2p is 0 commits ahead of
    main; no FINAL_FINDINGS.md or PR_FINDINGS_BRIEF.md exists on the SDK. There is
    no separate in-flight candidate, so main HEAD was audited and adopted.
  blocking_defect_found_in_previous_pin: |
    derive() appended the PARENT's hop_trace to every child. Those hops carry the
    parent's packet_id, so validate_hop_trace rejects them -- every dispatch packet
    Gate emitted was rejectable by any SDK worker. Fixed upstream in 1d52369.

RETRY:
  converge_gate_attempts: 1
  replay_safe_actions: [] (default: nothing is replay-safe)
  idempotency_required: true (necessary but NOT sufficient)

DEADLINE:
  one_monotonic_deadline: true
  worker_transport_remaining_budget: true

IDEMPOTENCY:
  namespace: tenant.org_id + action + idempotency_key
  durable: false (and not represented as durable)
  cross_tenant_test: PASS

REPLAY:
  window_enforced: true (on the hot path, no manual prune required)
  bounded_state: true (max_entries, oldest-first eviction)

SECURITY:
  production_trust_boundary: UNPROVEN from repository evidence
  signatures_required: enforced in staging/prod unless a network boundary is
    explicitly asserted; require_signature with no key material is also rejected
  external_auth_boundary: no staging/prod manifest, mesh, or ingress config exists
    in this repository; none was invented

EIE:
  registered: yes (enrichment-engine)
  owner: eie
  converge_routable: PASS

TEST EVIDENCE:
  - command: pip install -e ".[dev]"
    result: PASS
  - command: make lint
    result: PASS
  - command: make typecheck
    result: PASS (mypy strict, 70 files)
  - command: make contracts
    result: PASS
  - command: make test-unit
    result: PASS (140)
  - command: make test-integration
    result: PASS (24)
  - command: make pr
    result: PASS (292 tests; baseline was 181)
  - command: python -m build --wheel
    result: PASS
  - command: clean-venv install of built wheel + route/readiness smoke
    result: PASS

REAL RUNTIME:
  sdk_worker_round_trip: PASS (SDK validate_transport_packet at the worker end)
  eie: NOT_RUN (no live EIE process available)
  deployed_gate: NOT_RUN

SCOPE DRIFT:
  Two changes beyond the literal required list, both named in FINAL_FINDINGS.md
  rather than buried:
    - Dispatcher wiring: the pooled client and the per-node concurrency limiter
      were constructed at startup and never passed to the Dispatcher. In scope
      because the deadline must reach the ACTUAL transport, and the actual
      transport was not the one the app had built.
    - Worker transport error mapping: the new typed errors fell through to 500
      internal_error, reporting an upstream failure as a Gate bug. Completes the
      "preserve actionable cause chains" requirement.
  No domain translation, no direct application->worker path, no node->node path,
  no provider retry logic, no EIE domain logic, no new transport protocol.

NEXT STRAIGHT_LINE_MOVE:
  Open the Gate_SDK issue from GATE_SDK_REQUIRED_DELTA.md section 2 and bump EIE's
  SDK pin to d09fe58. Both are small, unblock the last classified gap, and are
  prerequisites for replacing the SDK fixture with a live Gate<->EIE round trip.
