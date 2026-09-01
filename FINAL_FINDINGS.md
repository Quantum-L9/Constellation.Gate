# FINAL_FINDINGS — Constellation.Gate Routing & Execution-Control Closure

# Executive Verdict

**Local: GO. Routing contract: GO. Runtime: PROOF_PENDING. Merge: APPROVE.
Release set: PENDING (one external SDK capability outstanding).**

The declared architecture held up under audit: Gate is the sole routing
authority, accepts and emits only canonical `TransportPacket`, treats domain
payloads as opaque, and locks `converge → eie`. Every one of those is now backed
by an executable test rather than by documentation.

Two findings materially change the picture from what was anticipated:

1. **The headline item — Gate's manual worker HTTP — is externally blocked, not
   deferrable by choice.** Gate_SDK has no Gate-authorized worker transport
   primitive at the current pin or at main HEAD. Its only outbound surface,
   `GateClient`, explicitly refuses peer URLs by design. Per ADR-GATE-005's stop
   rule, the gap is reported (`GATE_SDK_REQUIRED_DELTA.md`) and **not** concealed
   behind a new Gate-local abstraction.

2. **Gate's worker dispatch was, in fact, broken end-to-end — and no existing
   test could see it.** Running Gate's derived packet through the *real* SDK
   worker validators (instead of Gate's own fixtures, which agreed with Gate)
   showed that every Gate→worker dispatch would be **rejected by any SDK-based
   worker**, for two independent reasons. Both are fixed. This was not on the
   task list; it is the most consequential thing in this pass.

The three anticipated hardening gaps (retry, idempotency namespace, replay
window) were all real, all confirmed, and all closed.

# Repository / Branch / Candidate HEAD

| Field | Value |
|---|---|
| Repository | `Quantum-L9/Constellation.Gate` |
| Branch | `claude/gate-routing-sdk-transport-4btf4g` |
| Candidate HEAD | `07c86a22b3b4f3a881c8f0a50a97b684a0179d4f` |
| Base | `origin/main` @ `545eda4259121dbce85c084385f68d00632981d7` |
| Python | 3.12 (repo requires `>=3.12`; container default is 3.11 — a 3.12 venv is required to run anything here) |

# Gate_SDK Version

| Field | Value |
|---|---|
| Previous pin | `a770e8531dc1c59ce01e1dbb0f4162785d9dda89` |
| **New pin** | `d09fe58a6cd68ef8aa883896c68badc95f96e090` |
| Pin style | exact 40-char commit; `@main` forbidden and asserted |
| Anticipated "SDK work in flight" | **not present** — the SDK branch `claude/gate-routing-sdk-transport-4btf4g` has zero commits beyond `origin/main`, and no `FINAL_FINDINGS.md` / `PR_FINDINGS_BRIEF.md` exists there |

The pin was advanced because the old pin is **functionally incompatible with any
SDK worker** (see *Packet Derivation / Hop State*). The full `a770e853..d09fe58`
delta was reviewed: two transport corrections (both required), plus additive
capability-client/observability code and a `cryptography<45` bound. Nothing in
the delta removes or alters an API Gate uses.

# Routing Authority

`GO`. Gate remains the sole routing authority.

- Ingress rejects node→node and client→worker packets (`test_no_direct_node_to_node`,
  `test_gate_only_routing`).
- Only Gate mints worker-addressed packets (`test_gate_dispatch_authority`).
- Registry/resolver knowledge stayed in Gate. **This was deliberate**: the task
  framing is right that Gate *must* know worker URLs — routing is its authority.
  The thing being removed is Gate owning a second implementation of packet
  transport *after* the routing decision. That seam is now guarded explicitly.

# Action Ownership Matrix

| Canonical action | Required owner | Enforcement |
|---|---|---|
| `converge` | `eie` | fail-closed at registration + at readiness |
| `graph-inference-result` | `eie` | fail-closed |
| `match` / `sync` / `outcomes` | `ceg` | fail-closed |

Registration metadata cannot override canonical ownership (ADR-GATE-013);
same-owner replicas are permitted; cross-owner claims raise
`ActionOwnershipError`. Ownership is now **also** checked at readiness, not only
at registration — a node whose advertised actions drift post-registration is
caught (`test_wrong_owner_claiming_converge_is_not_routable`).

# Domain Payload Opacity

`GO`. Proven, not asserted.

- Static scan of all 69 production modules: **zero** occurrences of
  `entity_snapshot`, `EnrichRequest`, `EnrichResponse`, `final_fields`,
  `writeback`, `odoo`, `crm`. No production module indexes a packet payload.
- Behavioural proof uses an adversarial payload containing the exact field names
  a translating Gate would rewrite (`status`, `final_fields`, `entity_snapshot`,
  `state`, `fields`, `entity`), plus unicode, empty keys, explicit nulls, and
  deep nesting. Byte-identical through ingress → derivation → worker packet, and
  the caller's own dict is not mutated.
- A per-file drift guard now fails the build if any production module acquires
  domain vocabulary.

**Non-blocking observation:** `orchestration/workflow_engine.py::_merge_payload`
reads `response.get("data")` under the `merge_results` strategy. `data` is a
generic composition convention rather than domain vocabulary, and it is opt-in
per workflow step, but it is the one place Gate makes an assumption about payload
*shape*. Currently inert — no workflow config is loaded by default. Recorded, not
changed, because changing composition semantics is outside this pass.

# Gate→Worker Transport State

**`BLOCKED_EXTERNAL_SDK_CAPABILITY`** — the one item in the contract that could
not be closed, and deliberately not faked.

`GateClient` is node→Gate only and, by its own contract, "never accepts an
arbitrary peer URL". There is no Gate-authorized worker transport primitive at
`a770e853` or at `d09fe58`. Gate therefore still owns `_post_dispatch_packet`.

What was done instead of a cosmetic refactor:

- the transport call is confined to **one** adapter method;
- an architecture guard fails if any second production module learns to POST a
  canonical packet — verified by planting a probe module, watching the guard
  fail, and removing it;
- the guard's allow-list is a ratchet asserted to be exactly
  `{routing/worker_transport.py}`, so it can shrink but not silently grow. The
  mechanics moved out of `routing/dispatch.py` into a dedicated seam so the
  routing decision (*where*) and the transport (*how*) are separable and the
  pending SDK migration is a one-function swap; the allow-list moved with them,
  same size, and gained assertions that the dispatcher cannot reacquire HTTP,
  status mapping, or response decoding;
- the guard distinguishes Gate's own **inbound** `@app.post("/v1/execute")` route
  from an **outbound** awaited client call (an earlier string-match version
  wrongly flagged `api/main.py`).

Exact requested API: `GATE_SDK_REQUIRED_DELTA.md`.

# Packet Derivation / Hop State

`GO` — **after fixing two blocking defects that no pre-existing test could
detect.** Both were found only by running Gate's output through the real SDK
worker validators.

**Defect 1 — missing `route_kind` (Gate-side).** The SDK's
`validate_execute_ingress_packet()` requires `provenance.route_kind` and accepts
only `external_ingress` on `/v1/execute`. Gate's dispatcher never set it. Every
Gate dispatch would have been rejected by every SDK-based worker. Fixed in
`routing/dispatch.py`.

**Defect 2 — hop inheritance across `derive()` (SDK-side, at the old pin).** At
`a770e853`, `derive()` carried parent hops into the child; the inherited hop kept
the *parent's* `packet_id`, so the worker's `validate_hop_trace()` raised
`hop packet_id does not match packet header packet_id`. The single transport diff
between the old pin and main is exactly this fix. Resolved by advancing the pin.

A third, latent defect rides along in the same pin advance: `_canonicalize` used
local-time datetimes, making `transport_hash` machine-dependent (Mac EDT vs
Docker UTC) — a class of failure that would have appeared as intermittent
integrity errors between a developer machine and a container.

Now proven per dispatch: new `packet_id`, correct `parent_id` / `root_id` /
`generation` / `causation`, Gate source, worker destination, Gate `reply_to`,
payload preserved, tenant preserved, exactly one dispatch hop bound to the
child's own `packet_id`.

# Retry State

`GO`. Confirmed exactly as anticipated, and closed.

`RetryPolicy()` defaulted to **3 attempts on `TimeoutError`** and wrapped *every*
action generically. A timeout is precisely the failure where Gate cannot know
whether the worker already applied the effect, so multiplying the operation was
the least safe response available, not the most conservative.

| Path | Before | After |
|---|---|---|
| `converge` | 3 attempts | **1** |
| any action, no explicit contract | 3 attempts | **1** |
| declared replay-safe + idempotency key | 3 | 3 (unchanged, now deliberate) |
| declared replay-safe, **no** key | 3 | **1** |

`GATE_REPLAY_SAFE_ACTIONS` is **empty by default** — nothing is replay-safe until
a contract says so. `converge`, `match`, `sync`, `outcomes`,
`graph-inference-result` are recorded as worker-owned-retry and are disjoint from
the replay-safe set by assertion. An idempotency key alone never enables replay:
a key makes a replay *recognisable*, not *harmless*.

`RetryPolicy` was kept intact for explicit workflow contracts, per the contract's
instruction not to delete it. `ExecuteService.retry_policy` is now a **ceiling
template**: it can narrow the attempt budget but never widen it, asserted in both
directions.

**Mutation-verified:** restoring the old behaviour makes 14 of these tests fail.

# Deadline State

`GO`.

One monotonic deadline (`time.monotonic`, not wall clock) is derived from
`header.timeout_ms` after ingress validation and threaded to the actual transport
call, which receives `min(remaining budget, node cap)`.

The contract explicitly warned against accepting `asyncio.wait_for` as evidence,
and that warning was well placed: the outer `wait_for` cancels the coroutine from
outside while the *socket* timeout could still be a fresh full value. The tests
therefore assert the timeout argument handed to the transport call itself — 30s
budget, 25s node cap, 28s already spent yields **2.0s**, not 25s. Retry sleeps
draw from the same budget and will not sleep past it to start an attempt that
cannot finish. An expired deadline refuses to open a connection at all.

# Idempotency State

`GO`.

The cache keyed on the **raw caller-supplied string**. Two tenants sending
`"order-1"` collided, and one tenant reusing a key across unrelated actions
collided — a cross-tenant data leak presenting as a cache hit.

Now namespaced `(tenant.org_id, canonical action, key)`, using the canonical
integrity-hashed `packet.tenant` rather than any caller-controlled payload field,
joined with a separator that cannot appear in the components (so `("a|b","c")`
and `("a","b|c")` cannot collide). Proven: cross-tenant isolation, cross-action
isolation, and that a raw unnamespaced key no longer resolves.

**Explicitly documented as NOT durable** (ADR-GATE-010): process-local only, with
a `DURABLE = False` module constant. No distributed infrastructure added.

# Replay State

`GO`.

The declared 300s window was **advertised but never enforced** — expiry lived
only in `prune()`, which nothing on the hot path called. Consequences: a packet
id was rejected forever rather than for the window, and the seen-set grew without
bound for the life of the process.

`check_and_record()` now expires inline. Proven with an injectable clock: rejected
at 299s, accepted at 301s, and 500 packets over 500 simulated seconds against a
10s window retain ≤12 entries rather than 500. `prune()` is retained for
operators but is no longer load-bearing.

# Ingress Security / Trust Boundary

**Before: `UNPROVEN` and actively hazardous.**

| Evidence | Finding |
|---|---|
| `require_signature` default | `false` |
| `L9_DEV_MODE` in the only shipped compose | `true` |
| Terraform `allowed_cidrs` default | **`["0.0.0.0/0", "::/0"]`** |
| staging/prod deployment manifest | **none exists** |

An internet-reachable port whose only admission test is "the bytes parse".

**After:** staging/prod fail closed at settings construction unless one boundary
is proven — verified signatures *with* keys configured, or an explicitly attested
network boundary (`L9_TRUSTED_INGRESS_BOUNDARY=network` plus
`..._EVIDENCE` naming the enforcing mechanism). Also refused: `dev_mode` in
staging/prod, and `require_signature=true` with no verifying keys (which would
verify nothing while appearing secure). `local` / `dev` / `test` are unaffected.

This makes the repository-side default safe. It does **not** by itself prove a
production boundary exists — that requires deployment evidence, which is not in
this repository. **Production ingress remains `NO_GO` until an operator declares
one**; the difference is that Gate now refuses to start rather than silently
accepting anonymous traffic.

# Registration State

`GO`. Ownership fails closed; generic registration schema unchanged (no
EIE-specific schema added). The SDK's `build_registration_payload` shape
(`owner`, `supported_actions`, `internal_url`, `health_endpoint`, `timeout_ms`,
`max_concurrent`) is accepted by Gate's registration path as-is.

# EIE Routability

`PROOF_PENDING` — and this is a genuine gap, not a formality.

`converge → eie` is proven **routable in principle**: given a healthy,
`owner=eie`-tagged registration, the resolver selects it and dispatch reaches it.
New `runtime/routing_readiness.py` answers "can Gate route converge right now?"
and distinguishes *registered-but-unhealthy* from *never-registered* (it reads
`snapshot()` rather than `resolve_destination()`, which hides unhealthy nodes —
two different operational problems with two different fixes).

What is **not** proven: no live EIE was reachable in this environment, and the
shipped `node_registry.yaml` contains no `eie` node and is not loaded by the
runtime at all (registration is runtime-only, via `/v1/admin/register`). A canary
must run the readiness check against the real registry before traffic.

That check is now reachable: `GET /v1/ready` returns the report and answers 503
while a required action is not routable. Previously `routing_readiness()`
computed the right answer but no route exposed it, so nothing outside the process
could ask — a canary would have discovered an un-routable Gate on its first real
request instead of on its probe. `/v1/health` deliberately stays a pure liveness
signal; folding routability into it would pull Gate out of rotation whenever a
worker blips.

# Workflow State

Workflows share the corrected dispatcher, so they inherit the attempt budget and
`route_kind`. They did **not** inherit the deadline, and an earlier revision of
this document claimed they did — that claim was wrong and is corrected here.

`ExecuteService` probes a collaborator's signature and passes the deadline only
to one that declares the parameter. `WorkflowEngine.execute` did not declare it,
so every workflow step ran with **no deadline at all**: an N-step workflow could
consume N x the per-node timeout inside a packet budget that claimed one. This
was invisible because sharing "the corrected dispatcher" is not the same as
receiving the budget — the dispatcher falls back to the node cap when handed
`deadline=None`.

The engine now declares the parameter, passes one budget object to every step,
and clamps a step's declared `timeout_ms` to what remains.
`tests/orchestration/test_workflow_deadline.py` asserts the signature itself, so
the probe cannot silently start missing again.

The `merge_results` payload-shape assumption is recorded above as non-blocking.
No workflow was broken to fix ordinary dispatch.

# Dependency / Installability Evidence

| Check | Result |
|---|---|
| `pip install -e ".[dev]"` (py3.12) | PASS |
| Clean wheel build (`python -m build`) | PASS |
| Install wheel into a fresh venv + import | PASS |
| SDK resolves at the exact new pin | PASS |
| `scripts/validate_sdk_pin.py` | PASS |

Note: a plain `pip install -e .` will **not** re-resolve the SDK when a stale
version is already present — advancing the pin needs
`--force-reinstall --no-deps` on the SDK. Worth knowing before a deploy silently
runs the old transport.

# Cross-Repository Runtime Evidence

`tests/integration/test_cross_repo_converge_round_trip.py` drives an
Odoo-shaped root packet through Gate ingress → resolver → Gate-authored child →
**the real SDK worker-side validators and handler execution path** → canonical
response → Gate response validation.

The worker half is `constellation_node_sdk.runtime.inbound_policy` and
`runtime.execution`, not a hand-written stand-in. That distinction is the entire
reason both interoperability defects were found.

| Level | Status |
|---|---|
| `sdk_worker_runtime_fixture` | **PASS** |
| `real_eie_runtime` | **NOT_RUN** (no live EIE available) |
| `deployed_gate` | **NOT_RUN** |

# Tests Actually Executed

| Command | Result |
|---|---|
| `ruff check src tests` | PASS |
| `ruff format --check src tests` | PASS (164 files) |
| `mypy src` (strict) | PASS (69 files) |
| `pytest -q` | **339 passed** |
| `pytest tests/…` (unit set) | 202 passed |
| `pytest tests/integration` | 13 passed |
| clean build + installed-package import | PASS |

Baseline on `origin/main` was 181 passed — but only after creating a 3.12 venv,
because `make` itself was broken (below).

**Two pre-existing tests were repaired, not relaxed** (classified per test-integrity
policy as *test defects* — assertions encoding a superseded contract):

1. `test_idempotency_returns_cached_response` seeded the raw key `"abc"`
   directly — the exact unsafe identity being removed. Replaced with six tests
   covering cross-tenant isolation, cross-action isolation, and explicit proof
   that a raw key no longer resolves.
2. `test_lineage_is_preserved_across_gate_reentry_and_dispatch` asserted the
   child carries **2** hops — encoding the pre-fix inheritance that broke worker
   validation. Now asserts the child carries exactly its own dispatch hop bound
   to its own `packet_id`, with lineage still carrying ancestry. Strictly
   stronger.

# Remaining Blocking Defects

None in this repository.

# Remaining Non-Blocking Defects

1. ~~Production dispatcher gets no pooled client and no per-node limiter.~~
   **FIXED** in the follow-up commit. `get_dispatcher()` now passes
   `node_limits=` and a `client_provider=`. The provider (rather than a `client=`)
   exists because the pool is only created at ASGI startup while the dispatcher
   is built during wiring; it resolves per dispatch and returns `None` outside a
   lifespan, so scripts and unit tests stay on the per-call path. It is
   deliberately not `lru_cache`d — caching would freeze the pre-startup `None`
   and permanently defeat the pool. Pinned by
   `tests/api/test_dispatcher_wiring.py`, including that the per-node limiter
   (the authoritative admission gate before a worker call) is the shared
   instance.
2. `workflow_engine._merge_payload` reads `response.get("data")` (payload-shape
   assumption; inert by default).
3. `DeadLetterQueue` is in-memory; observability only, not durable recovery. No
   documentation currently overstates it.
4. `node_registry.yaml` is shipped, references stale nodes (`enrich`,
   `cognitive_engine_graphs`), contains no `eie`, and is **not loaded by the
   runtime** — only checked for existence by `predeploy_check.py`. Misleading;
   recommend removing or wiring.

# External SDK Blockers

`gate_authorized_worker_packet_transport` — see `GATE_SDK_REQUIRED_DELTA.md`.
This is the sole reason the release set is not GO.

# Deferred Work

As scoped by the contract: durable/distributed Gate idempotency, durable
dead-letter infrastructure, queue redesign, registry database redesign,
generalized workflow redesign, `TransportSecurity` hash-envelope redesign.

# Scope Drift Audit

Three things were done that were not on the task list, each because the work
could not honestly be called complete without them:

1. **Repaired the `Makefile`.** It carried a stray markdown fence at line 33
   (`------------` … ` ```yaml `), so **every** target failed with
   `Makefile:33: *** missing separator. Stop.` — `make lint`, `make test`, and
   the `make pr` the contract mandates were all unrunnable on `main`. Contract
   §24 asks for a `pr` target; it cannot exist in a file that does not parse.
2. **Fixed `route_kind` and advanced the SDK pin.** Not optional polish: without
   both, Gate cannot successfully dispatch to any SDK worker.
3. **Made the trust boundary fail closed.** Contract §13 asks to prove the state;
   the state proved to be an internet-open port with no authentication, which is
   a finding that has to be acted on, not just recorded.

No domain translation, no direct application→worker path, no node→node path, no
provider retry logic, no EIE or Odoo domain logic, and no new transport protocol
were introduced.

# Merge Recommendation

**APPROVE.** All gates green (lint, format, strict mypy, 339 tests, clean build,
installed-package import). The one unfinished item is externally blocked, is
reported rather than concealed, and is guarded so it cannot drift.

# Release-Set Recommendation

**PENDING**, on two conditions:

1. `gate_authorized_worker_packet_transport` lands in Gate_SDK (transport
   closure), and
2. an operator declares a real production ingress trust boundary — Gate will now
   refuse to start in staging/prod without one.

Before canary, additionally: run the readiness check against the live registry
to confirm `converge → eie` actually resolves, and consider the pooled-client
wiring under *Non-Blocking* first.

# Next Straight-Line Move

Land the SDK-side `send_gate_authored_packet` primitive from
`GATE_SDK_REQUIRED_DELTA.md`, then replace the body of `_post_dispatch_packet`
and shrink `WORKER_TRANSPORT_ADAPTER` to empty. Everything on Gate's side is
already shaped for that single substitution.

# Machine-Readable Summary

```yaml
repository: Quantum-L9/Constellation.Gate
branch: claude/gate-routing-sdk-transport-4btf4g
candidate_head: "07c86a22b3b4f3a881c8f0a50a97b684a0179d4f"
gate_sdk:
  pinned_sha: "d09fe58a6cd68ef8aa883896c68badc95f96e090"
  previous_sha: "a770e8531dc1c59ce01e1dbb0f4162785d9dda89"
  installed_package: PASS
  worker_transport_sdk_owned: false
  external_capability_gap: gate_authorized_worker_packet_transport
routing:
  sole_authority: true
  direct_peer_routing: false
  converge_owner: eie
  domain_payload_opaque: true
  gate_authored_worker_packets: true
  route_kind_set: external_ingress
retry:
  generic_whole_operation_retry: false
  converge_gate_attempts: 1
  replay_requires_idempotency: true
  retry_requires_explicit_safety: true
  replay_safe_actions: []
deadline:
  one_monotonic: true
  downstream_uses_remaining_budget: true
idempotency:
  namespace:
    - tenant
    - action
    - idempotency_key
  process_local: true
  represented_as_durable: false
  cross_tenant_safe: true
replay:
  window_enforced_hot_path: true
  bounded_state: true
security:
  production_trust_boundary: UNPROVEN
  repository_default_fails_closed: true
  packet_validation: true
  canary_safe: false
registration:
  ownership_fail_closed: true
  eie_owner: eie
  converge_routable: PROOF_PENDING
validation:
  lint: PASS
  format: PASS
  typecheck: PASS
  unit: PASS
  integration: PASS
  full_suite: PASS
  test_count: 339
  installed_package: PASS
  cross_repo: PASS
  real_eie_runtime: NOT_RUN
  make_pr: PENDING
blocking_defects: []
non_blocking_defects:
  - production dispatcher receives no pooled client and no per-node limiter
  - workflow merge_results assumes a response "data" key
  - dead_letter_queue is in-memory and observability-only (now bounded at 1000 entries, oldest-first)
  - node_registry.yaml is stale and not loaded by the runtime
external_blockers:
  - gate_authorized_worker_packet_transport
verdict:
  local: GO
  routing_contract: GO
  runtime: PROOF_PENDING
  merge: APPROVE
  release_set: PENDING
next_move: >
  Land send_gate_authored_packet in Gate_SDK, then replace the body of
  _post_dispatch_packet and shrink WORKER_TRANSPORT_ADAPTER to empty.
```
