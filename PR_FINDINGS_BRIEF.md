```
CONSTELLATION.GATE PR FINDINGS BRIEF

REPOSITORY:
  name: Quantum-L9/Constellation.Gate
  branch: claude/gate-routing-sdk-transport-4btf4g
  candidate_head_sha: 316f6faf2c122e5032495916dc4dfe9a0461fd5c
  code_head_validated_by_make_pr: 2f1a76487da518c0722629ccdb4f558b8573e09f  # tip adds this brief only
  base: origin/main @ 545eda4259121dbce85c084385f68d00632981d7

MAKE PR:
  role: validation_gate          # lint + typecheck + test; opens no remote PR
  result: PASS
  failed_phase_if_any: none
  note: >
    The `pr` target did not exist and could not have: the Makefile carried a
    stray markdown fence at line 33, so EVERY target failed with
    "Makefile:33: *** missing separator. Stop." Repaired, then `pr` added.

REMOTE PR:
  created: false                 # not requested; no PR opened
  number: null
  url: null
  base: main
  remote_head_sha: 316f6faf2c122e5032495916dc4dfe9a0461fd5c   # pushed, matches local

VERDICT:
  routing: GO
  transport: BLOCKED_EXTERNAL_SDK_CAPABILITY
  domain_opacity: GO
  action_ownership: GO
  retry: GO
  deadline: GO
  idempotency: GO
  replay: GO
  ingress_security: repository_default_now_fails_closed; production UNPROVEN
  gate_sdk: pin advanced and proven
  eie_routability: PROOF_PENDING
  local: GO
  merge: APPROVE
  release_set: PENDING

FOLLOW-UP COMMIT (ported from a parallel implementation of the same contract):
  - workflow deadline: WorkflowEngine.execute did not declare `deadline`, so the
    ExecuteService signature probe skipped it and every workflow step ran with NO
    budget. An earlier revision of FINAL_FINDINGS.md claimed workflows inherited
    the deadline; that claim was wrong and is corrected there.
  - GET /v1/ready: routing_readiness() was computed but unreachable — no route
    exposed it, so a canary could not ask before sending real traffic
  - typed worker transport errors in routing/worker_transport.py; the dispatcher
    caught httpx.TransportError, of which httpx.TimeoutException is a SUBCLASS,
    so one slow response marked a working worker unhealthy and ejected it
  - worker transport failures now map to 502 (504 on timeout) instead of 500
  - `make lint` now runs `ruff format --check`, which CI enforces and it did not
  - dead-letter queue bounded at 1000 entries, oldest-first

IMPLEMENTED:
  - route_kind="external_ingress" on Gate-authored worker packets
  - SDK pin a770e853 -> d09fe58 (derive hop reset + UTC-stable transport hash)
  - whole-operation retry defaults to 1 attempt; replay needs explicit safety + key
  - one monotonic packet deadline threaded into the real worker transport call
  - idempotency namespaced by (tenant.org_id, action, key); documented non-durable
  - replay window enforced inside check_and_record(); state bounded
  - staging/prod fail closed without a proven ingress trust boundary
  - runtime/routing_readiness.py: "can Gate route converge right now?"
  - architecture drift guards over domain vocabulary and the transport seam
  - Makefile repaired; `pr` / `pr-check` validation targets added

PROVEN:
  - Gate-derived packet accepted by the REAL SDK worker validators (round trip)
  - adversarial domain payload byte-identical through ingress -> derive -> worker
  - converge attempted exactly once even with an idempotency key
  - transport call receives 2.0s when 28s of a 30s budget is spent (node cap 25s)
  - cross-tenant and cross-action idempotency isolation
  - replay: rejected at 299s, accepted at 301s; 500 packets/10s window -> <=12 kept
  - drift guard fails on a planted offender, passes on the legitimate inbound route
  - retry tests mutation-verified: 14 fail when the old behaviour is restored

BLOCKERS:
  - none in this repository

NON_BLOCKING:
  - get_dispatcher() passes neither pooled client nor per-node limiter, so
    AsyncHttpClientManager and PerNodeLimiterManager are dead in production
    (fresh httpx client per dispatch; per-node limits never apply)
  - workflow _merge_payload assumes a response "data" key (inert by default)
  - DeadLetterQueue is in-memory; observability only
  - node_registry.yaml is stale, has no eie, and is not loaded by the runtime

GATE_SDK:
  exact_sha: d09fe58a6cd68ef8aa883896c68badc95f96e090
  previous_sha: a770e8531dc1c59ce01e1dbb0f4162785d9dda89
  worker_transport_sdk_owned: false
  external_capability_gap: gate_authorized_worker_packet_transport
  anticipated_sdk_candidate: NOT_PRESENT
  note: >
    The expected in-flight SDK transport work has not landed: the SDK branch of
    the same name has zero commits beyond origin/main and no findings files.
    GateClient is node->Gate only and by contract "never accepts an arbitrary
    peer URL", so no Gate->worker primitive exists to consume. Reported in
    GATE_SDK_REQUIRED_DELTA.md rather than concealed behind a new Gate-local
    transport abstraction.

RETRY:
  converge_gate_attempts: 1
  replay_safe_actions: []        # empty by default; nothing is safe until declared
  idempotency_required: true     # necessary but NOT sufficient
  worker_owned_retry: [converge, graph-inference-result, match, sync, outcomes]

DEADLINE:
  one_monotonic_deadline: true
  worker_transport_remaining_budget: true
  clock: time.monotonic
  note: asyncio.wait_for was NOT accepted as evidence; the timeout argument
        handed to the transport call is asserted directly

IDEMPOTENCY:
  namespace: [tenant.org_id, canonical_action, idempotency_key]
  durable: false
  cross_tenant_test: PASS

REPLAY:
  window_enforced: true
  bounded_state: true

SECURITY:
  production_trust_boundary: UNPROVEN
  signatures_required: false by default; now REQUIRED in staging/prod unless a
                       network boundary is explicitly attested
  external_auth_boundary: declarable via L9_TRUSTED_INGRESS_BOUNDARY=network
                          plus L9_TRUSTED_INGRESS_BOUNDARY_EVIDENCE
  evidence_found: terraform allowed_cidrs defaults to ["0.0.0.0/0","::/0"] while
                  require_signature defaulted to false and the only shipped
                  compose sets L9_DEV_MODE=true; no staging/prod manifest exists

EIE:
  registered: NOT_RUN (no live EIE in this environment)
  owner: eie (canonical, fail-closed)
  converge_routable: PROOF_PENDING — proven in principle, unproven against a
                     live registry; run routing_readiness before canary

TEST EVIDENCE:
  - command: ruff check src tests
    result: PASS
  - command: ruff format --check src tests
    result: PASS (169 files)
  - command: mypy src            # strict
    result: PASS (70 files)
  - command: pytest -q
    result: PASS (367 passed; baseline on main was 181)
  - command: pytest tests/integration
    result: PASS (13 passed)
  - command: python -m build --wheel + install into a clean venv + import
    result: PASS
  - command: python3 scripts/validate_sdk_pin.py
    result: PASS
  - command: PR_REMEDIATE=0 make pr
    result: PASS

REAL RUNTIME:
  sdk_worker_round_trip: PASS    # real constellation_node_sdk worker validators
  eie: NOT_RUN
  deployed_gate: NOT_RUN

SCOPE DRIFT:
  three items outside the stated task list, each load-bearing:
   1. Makefile repair — every target failed to parse, so the contract-mandated
      `make pr` was impossible without it
   2. route_kind + SDK pin advance — without both, Gate cannot dispatch to any
      SDK worker at all
   3. trust boundary fail-closed — the audit asked to prove the state; the state
      was an internet-open port with no authentication
  no domain translation, no direct app->worker or node->node path, no provider
  retry logic, no EIE/Odoo domain logic, no new transport protocol

NEXT STRAIGHT_LINE_MOVE:
  Land send_gate_authored_packet in Gate_SDK (GATE_SDK_REQUIRED_DELTA.md), then
  replace the body of routing/worker_transport.post_worker_packet and shrink
  WORKER_TRANSPORT_ADAPTER to empty. Everything Gate-side is already shaped for
  that single substitution: Dispatcher delegates and holds no HTTP, and the
  drift guard asserts it cannot reacquire any.
```
