# FINAL_FINDINGS — Constellation.Gate Routing & Execution-Control Closure

# Executive Verdict

**Local: GO. Routing contract: GO. Transport closure: GO. Runtime: GO for the
SDK rail, PROOF_PENDING for live processes. Merge: APPROVE. Canary: NO-GO.**

The external capability this repository was blocked on has landed. Gate_SDK
`bfe6642` ships `GateDispatchTransport.send_gate_authored_packet()`, so
`routing/worker_transport.py` — the Gate-local adapter written explicitly to be
deleted when that primitive existed — is **deleted**, not deprecated. Gate now
owns the routing decision and nothing else about the hop: no HTTP, no
serialization, no status mapping, no response parsing. The shadow-transport
allow-list reached **zero**.

Three things in this pass are worth more than the migration itself:

1. **The deadline split is closed, and it was real.** `derive()` never set
   `timeout_ms`, so a child packet advertised the *root* budget (30s) while Gate
   waited only the bounded remainder (2s). A worker was being told it had
   fifteen times the time Gate would actually give it. The SDK takes no timeout
   parameter by design — it derives the socket deadline from `header.timeout_ms`,
   and the worker runtime bounds its handler with the same field — so writing
   the bounded budget into the child collapses all three numbers into one
   (`INV-GATE-DOWNSTREAM-DEADLINE-IDENTITY`).

2. **The test suite stopped agreeing with itself.** Gate's dispatch tests
   answered with hand-built response bodies, which cannot prove interoperability:
   a fake returns whatever the test wants, including things no SDK worker would
   ever send. Every one now runs against the real SDK ingress policy and
   execution path. This is the same class of blindness that hid the two transport
   defects found in the previous pass, removed at its source rather than patched
   again.

3. **The authority boundary is proven negative, before I/O.** Six ways of not
   being a Gate dispatch are each asserted to be refused with **zero** network
   requests. A check that fired after the POST would already have delivered the
   packet.

Superseded by this pass — do not carry forward from earlier findings:

| Stale claim | Status |
|---|---|
| `gate_authorized_worker_packet_transport` missing from Gate_SDK | **FALSE** — shipped in `bfe6642` |
| `worker_transport_sdk_owned: false` | **FALSE** — now `true` |
| `external_capability_gap: gate_authorized_worker_packet_transport` | **CLOSED** — now `null` |
| `next_move: land send_gate_authored_packet` | **DONE** — consumed here |
| Gate owns `_post_dispatch_packet` / `post_worker_packet` | **FALSE** — module deleted |

What has **not** changed: Gate's production ingress trust boundary is still
unproven, and no live EIE or deployed Gate has run. Those remain the canary
blockers, and neither is weakened below.

# Repository / Branch / Candidate HEAD

| Field | Value |
|---|---|
| Repository | `Quantum-L9/Constellation.Gate` |
| Branch | `claude/gate-sdk-transport-adoption-ay1sc4` |
| Candidate HEAD | `3b5c959568e904ded02d3243d9efce24d7257e34` |
| Branched from | `claude/gate-routing-sdk-transport-4btf4g` @ `56c9cff1daaf6f57883e318c923dd0599f42853e` |
| Base | `origin/main` @ `545eda4259121dbce85c084385f68d00632981d7` |
| Python | 3.12 (repo requires `>=3.12`; container default is 3.11 — a 3.12 venv is required to run anything here) |

The prior audited head recorded in the delta contract (`07c86a22`) was **stale**:
the working branch had advanced four commits to `56c9cff` (transport seam,
workflow deadline, readiness route, typed worker errors, pooled client and
per-node limiter wiring). This branch continues that work rather than restarting
from `main`, which would have discarded ~3,900 lines of audited change.

# Gate_SDK Version

| Field | Value |
|---|---|
| Previous pin | `d09fe58a6cd68ef8aa883896c68badc95f96e090` |
| **New pin** | `bfe6642062a85a720ad8c25e96446d4df1c299ac` |
| Source | Gate_SDK PR #40, branch `claude/gate-sdk-transport-closure-u2klcf` |
| Merged to SDK `main` | **No** — the pin targets an unmerged PR head, deliberately and exactly |
| Pin style | exact 40-char commit; `@main` forbidden and asserted by `scripts/validate_sdk_pin.py` |

Provenance was verified rather than assumed. `pip install -e` can silently
re-resolve a git pin, so the installed distribution's own record was read:

```json
{"url": "https://github.com/Quantum-L9/Gate_SDK.git",
 "vcs_info": {"vcs": "git",
              "commit_id": "bfe6642062a85a720ad8c25e96446d4df1c299ac",
              "requested_revision": "bfe6642062a85a720ad8c25e96446d4df1c299ac"}}
```

`GateDispatchTransport` resolves to
`.venv/lib/python3.12/site-packages/constellation_node_sdk/gate_authority/dispatch.py`,
and `send_gate_authored_packet` is present with the signature the migration was
written against.

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

`GO`. **Closed.** The Gate-local adapter is gone.

```
producer -> Gate_SDK -> Constellation.Gate
                             |  owns the routing decision
                             v
                        resolves worker, derives child packet
                             |
                             v
                   Gate_SDK GateDispatchTransport
                             |  owns the transport hop
                             v
                        worker SDK runtime
```

| Property | Value | Evidence |
|---|---|---|
| `worker_transport_sdk_owned` | `true` | `routing/dispatch.py` calls `send_gate_authored_packet` |
| Direct `httpx` POST in Gate production | **none** | `test_worker_dispatch_http_stays_in_the_single_transport_adapter` |
| Manual packet JSON decode | **none** | `test_dispatcher_delegates_transport_and_owns_no_http` |
| Manual response packet validation | **none** | same; `TransportPacket.model_validate` is absent from `dispatch.py` |
| Shadow-transport allow-list | **empty** | `test_transport_adapter_surface_is_empty` |
| Adapter module | **deleted** | `test_no_gate_local_worker_transport_module_exists` |
| Network attempts per dispatch | **1** | SDK performs exactly one POST; asserted via `worker.request_count` |
| Reusable client | `true` | `test_the_pooled_client_is_reused_across_dispatches_and_never_closed` |

`dispatch.py` still imports `httpx`, for the type of the client Gate injects. It
performs no request; the drift guard keys on an awaited `.post`, not on the
import.

**The ratchet was widened, not just zeroed.** The original guard keys on the
literal string `/v1/execute`, which a re-implementation could simply spell
differently. A second guard now fails any module that performs an outbound POST
**and** revives a canonical packet from a body — the pairing *is* canonical
transport, whatever the URL says. It deliberately does not ban
`TransportPacket.model_validate` outright: Gate legitimately decodes its own
inbound ingress body (`boundary/transport_codec.py`) and revives packets from its
idempotency cache (`services/execute_service.py`). A blanket ban would flag both
and teach the next reader that ingress decoding is drift.

Both guards were mutation-checked: adding a module that POSTs to
`/v1/execute` and parses the reply fails them.

## Typed failures

Gate no longer touches `httpx.TransportError`, `httpx.TimeoutException`, or
`response.raise_for_status()`. It catches the SDK hierarchy and maps outcomes to
routing state:

| SDK error | Gate response | Node health |
|---|---|---|
| `WorkerConnectionError` | 502 | **marked unhealthy** |
| `WorkerTimeoutError` (also `TimeoutError`) | 504 | untouched |
| `WorkerHTTPError` | 502 | untouched |
| `WorkerResponseError` | 502 | untouched |
| `GateDispatchSecurityError` (inbound) | 502 `worker_response_untrusted` | untouched |
| `GateDispatchSecurityError` (outbound) | 500 | untouched |
| `GateDispatchAuthorityError` | **500** | untouched |
| `GateDispatchConfigurationError` | **500** | untouched |

The last two matter more than they look. Both subclass `ValueError`, and
`to_http_exception` maps `ValueError` to **400**. Matched in the wrong order, a
Gate-side packet defect would be reported to the caller as a client error they
can do nothing about. They are matched first, and a regression test pins it.

Failures are re-raised bare rather than with `raise ... from`, so the httpx cause
the SDK chained survives; Gate attaches only the resolved node name, which the
SDK cannot supply because it is told a target and never resolves one.

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

`GO`. One monotonic budget, and — new in this pass — **one number**.

`INV-GATE-DOWNSTREAM-DEADLINE-IDENTITY`: the timeout advertised to the worker in
the Gate-derived child packet is the same bounded remaining budget from which
Gate_SDK derives the actual worker network timeout. Severity: release-blocking.

```
root.header.timeout_ms
      -> Gate monotonic deadline
      -> remaining budget
      -> min(remaining, registered worker cap)
      -> worker_budget_ms
      -> child = derive(..., timeout_ms=worker_budget_ms)
      -> send_gate_authored_packet(child)
```

Worked case, asserted end to end:

| Stage | Value |
|---|---|
| Root budget | 30,000 ms |
| Gate elapsed before dispatch | 28,000 ms |
| Registered worker cap | 25,000 ms |
| **Child `header.timeout_ms`** | **2,000 ms** |
| **SDK socket timeout** | **2.0 s** |
| **Worker runtime handler budget** | **2.0 s** |

Previously the child advertised 30,000 ms in that same case. The tests assert the
header budget, the real socket deadline (read from `request.extensions["timeout"]`),
and the worker's own observed budget *together*, so the three cannot drift apart
again silently. Removing the `timeout_ms=` argument fails four of them.

A remainder that rounds below 1 ms is raised as `DeadlineExceeded` (→ 504) rather
than passed to the SDK, which would reject a non-positive budget as a
*configuration* error — reading as "Gate is misconfigured" when the operation had
simply run out of time.

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

`converge_routable: PASS` against the SDK rail. `real_eie: NOT_RUN`. Those are
two different claims and are reported separately on purpose.

`converge → eie` is proven routable *and dispatched*: given a healthy,
`owner=eie`-tagged registration, `action_routability()` reports it routable, the
resolver selects it, and a packet reaches it through
`GateDispatchTransport.send_gate_authored_packet` with the response returned
untranslated. Readiness and delivery are asserted against **one** registry in a
single test, because a readiness report is a registry-level statement that on its
own says nothing about a packet arriving — asserting them separately would let
"converge is routable to EIE" mean less than an operator reads it as.

`runtime/routing_readiness.py` answers "can Gate route converge right now?" and
distinguishes *registered-but-unhealthy* from *never-registered* (it reads
`snapshot()` rather than `resolve_destination()`, which hides unhealthy nodes —
two different operational problems with two different fixes).

What is **not** proven: the worker in that test is an SDK-backed stand-in, not a
live EIE process. No live EIE was reachable in this environment, and the
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

That harness is now shared (`tests/support/sdk_worker.py`) and used by every
dispatch test in the repository, not just this one. The worker half is
`constellation_node_sdk.runtime.inbound_policy` and `runtime.execution` behind a
real `httpx.AsyncBaseTransport` — not a hand-written stand-in. This is the
distinction that surfaced both interoperability defects in the previous pass;
generalising it removes the blindness rather than patching its symptoms.

Asserted across the hop:

| Property | Result |
|---|---|
| Payload unchanged | PASS |
| Tenant unchanged | PASS |
| Logical idempotency key unchanged | PASS |
| Correlation unchanged | PASS |
| Root lineage preserved | PASS |
| Child packet identity new | PASS |
| Causation points at the dispatched packet | PASS |
| Hop bound to the child's own `packet_id` | PASS |
| Worker source / response destination correct | PASS |
| Network requests | **exactly 1** |
| Deadline | **one number** across header, socket, and handler |

The response-relationship checks are the SDK's, not Gate's: a canonical,
correctly signed packet from the wrong worker, action, tenant, or operation is
still the wrong answer, and `send_gate_authored_packet` rejects it.

| Level | Status |
|---|---|
| `sdk_worker_runtime` | **PASS** |
| `signed_round_trip` | **PASS** |
| `real_eie_runtime` | **NOT_RUN** (no live EIE available) |
| `deployed_gate` | **NOT_RUN** |

`real_eie_runtime` is NOT_RUN, not PASS. The routability test uses an SDK-backed
worker registered as `eie`; it proves Gate resolves and dispatches correctly to
an EIE-owned node, and proves nothing about a live EIE process.

## Signed rail

`tests/integration/test_signed_worker_rail.py` runs the same hop with signing
required in both directions, then breaks it deliberately using a transport that
edits bytes between Gate and the worker.

| Case | Result |
|---|---|
| Signed dispatch accepted, signed response verified | PASS |
| Dispatch tampered in flight | refused at canonical decode, before ingress policy or handler |
| Response tampered in flight | `GateDispatchSecurityError(direction="inbound")` |
| Response signed by an unknown key | inbound security failure |
| Response signed by a trusted key used by the wrong signer | inbound security failure |
| Gate unable to sign | fails closed; **zero** requests |

The last three are the cases a naive "is there a signature?" check passes. A
forged answer is a security failure, never a parsing failure Gate might retry
into.

# Tests Actually Executed

| Command | Result |
|---|---|
| `ruff check src tests` | PASS |
| `ruff format --check src tests scripts` | PASS (175 files) |
| `mypy src` | PASS (69 files) |
| `pytest -q` | **389 passed** |
| `python scripts/validate_contracts.py` | PASS |
| `python scripts/validate_sdk_pin.py` | PASS (`bfe6642…`) |
| clean 3.12 venv install of `-e ./constellation-gate[dev]` | PASS |
| installed-package provenance (`direct_url.json`) | PASS — `commit_id` is the candidate |

Count moved 374 → 389 after the authority, signed-rail, and routability suites;
374 was itself the post-migration figure from the prior 339.

## Non-vacuity

New guards were mutation-tested rather than trusted:

| Mutation | Result |
|---|---|
| Add a production module that POSTs `/v1/execute` and parses the reply | 2 drift guards FAIL |
| Remove `timeout_ms=` from the child derivation | 4 deadline tests FAIL |

## Tests repaired, not relaxed

Classified per test-integrity policy as *test defects* — assertions encoding a
superseded contract — and in every case replaced with a strictly stronger claim.

1. `test_idempotency_returns_cached_response` seeded the raw key `"abc"` — the
   exact unsafe identity being removed. Replaced with six tests covering
   cross-tenant and cross-action isolation.
2. `test_lineage_is_preserved_across_gate_reentry_and_dispatch` asserted the
   child carries **2** hops, encoding the pre-fix inheritance that broke worker
   validation. Now asserts exactly its own dispatch hop.
3. Every dispatch test answering with a hand-built response body now answers
   with the real SDK runtime. The old fakes could not survive the SDK's response
   validation, which is the point: they were asserting against a worker that
   could not exist.

## Test deleted

`tests/routing/test_worker_transport.py` was removed because the module it
tested no longer exists. Its intent — that "down", "slow", and "answered badly"
stay three distinguishable outcomes — is not lost: it is carried forward in
`test_dispatch_node_health.py` against the SDK's typed errors, with two cases
added (`WorkerHTTPError` vs `WorkerResponseError`) and two new assertions that
the failure is attributed to the resolved node and that the SDK's `__cause__`
survives.

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

**None.** `gate_authorized_worker_packet_transport` — the sole entry here in the
previous pass — shipped in Gate_SDK `bfe6642` and is consumed by this branch.
`GATE_SDK_REQUIRED_DELTA.md` is retained as the historical record of the request
and is no longer an open item.

## External release-set debt (not this PR's to close)

1. **Cryptography advisory.** Gate_SDK retains a `cryptography>=43,<45` ceiling
   bounded by the Odoo.sh `pyOpenSSL` window, and carries an open dependency-audit
   finding. Resolving it by loosening the SDK constraint, changing Odoo's
   `pyOpenSSL`, or suppressing the finding is explicitly out of scope here. A
   functional transport merge recommendation is a different judgement from
   production-release authorization.
2. **Consumer adoption.** EIE and Odoo are still pinned to older SDK commits and
   their current findings are stale for the same reason Gate's were. Neither is
   modified by this PR.

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

**APPROVE.** All gates green: lint, format, `mypy src`, **389 tests**, contract
validation, SDK-pin validation, clean 3.12 install with verified package
provenance. No blocking defect remains in this repository, and no item is
deferred behind a Gate-local abstraction.

# Release-Set Recommendation

**Repository: GO. Canary: NO-GO.**

The transport condition that held this repository is closed. Two conditions
remain, neither of which this PR can discharge:

1. **Production ingress trust boundary — UNPROVEN.** Gate's repository default
   fails closed (it refuses to start in staging/prod without either signatures or
   an explicitly declared authenticated/private ingress), and that behaviour is
   untouched here. What is missing is *deployment evidence* that a real boundary
   exists. `canary_safe` stays `false` until an operator supplies it; it must not
   be set true on the strength of a green suite.
2. **No live runtime has run.** The SDK rail is proven; a live EIE and a deployed
   Gate are not. `real_eie: NOT_RUN`.

A repository verdict of GO and a canary verdict of NO-GO are consistent, not
contradictory: the code is merge-ready, the deployment is not yet authorized.

The Gate_SDK PR #40 `release_set: GO` should likewise not be read as
system-level release authorization. At the time it was written, no consumer had
adopted `bfe6642`, no real Odoo → Gate → EIE run had happened, and Gate's ingress
trust boundary was unproven. This PR closes the first of those three for Gate
only.

# Next Straight-Line Move

Bring **EIE** and **Odoo** onto this same SDK head (`bfe6642…`), then run the
four-repository real-runtime proof.

Both consumer updates should be mechanically smaller than this one:

* **EIE** — pin `bfe6642`, delete the bespoke Gate registration block in favour
  of the SDK's typed `register_node()` with `metadata.owner`, re-run the
  PostgreSQL/domain gates, then a real Gate round trip. Its stale finding is that
  Gate_SDK cannot send `metadata.owner`; `bfe6642` provides exactly that. Its
  claim that Odoo does not supply domain idempotency is also stale — Odoo already
  emits `EnrichRequest.idempotency_key` from durable enrichment-run identity.
* **Odoo** — pin the same SDK, replace manual `create_transport_packet` +
  `send_to_gate` with `GateClient.execute()`, drop the now-unnecessary raw
  `httpx` and legacy error handling, and run real Odoo 19. Its stale finding is
  that Gate_SDK has no `execute()`; it now has one.

After that: the live rail, the deployed ingress trust boundary, and the
cryptography advisory are what stand between the release set and canary.

# Machine-Readable Summary

```yaml
repository: Quantum-L9/Constellation.Gate
branch: claude/gate-sdk-transport-adoption-ay1sc4
candidate_head: "3b5c959568e904ded02d3243d9efce24d7257e34"
gate_sdk:
  pinned_sha: "bfe6642062a85a720ad8c25e96446d4df1c299ac"
  previous_sha: "d09fe58a6cd68ef8aa883896c68badc95f96e090"
  source_pr: Quantum-L9/Gate_SDK#40
  merged_to_sdk_main: false
  installed_package: PASS
  provenance_verified: direct_url.json commit_id matches
  worker_transport_sdk_owned: true
  external_capability_gap: null
routing:
  sole_authority: true
  direct_peer_routing: false
  converge_owner: eie
  domain_payload_opaque: true
  gate_authored_worker_packets: true
  route_kind_set: external_ingress
  worker_selection_owner: gate
  sdk_may_resolve_or_failover: false
worker_transport:
  direct_httpx_in_gate: false
  manual_response_packet_parsing: false
  api: GateDispatchTransport.send_gate_authored_packet
  network_attempts: 1
  reusable_client: true
  sdk_closes_external_client: false
  shadow_transport_allowlist: []
  adapter_module_deleted: true
deadline:
  one_monotonic: true
  child_header_uses_remaining_budget: true
  socket_uses_child_budget: true
  worker_runtime_uses_child_budget: true
  invariant: INV-GATE-DOWNSTREAM-DEADLINE-IDENTITY
retry:
  generic_whole_operation_retry: false
  converge_gate_attempts: 1
  hidden_sdk_retry: false
  replay_requires_idempotency: true
  replay_safe_actions: []
idempotency:
  namespace: [tenant, action, idempotency_key]
  process_local: true
  represented_as_durable: false
  cross_tenant_safe: true
replay:
  window_enforced_hot_path: true
  bounded_state: true
security:
  gate_authority_validation: PASS
  gate_authority_rejections_before_io: PASS
  signed_worker_round_trip: PASS
  tampered_dispatch_refused: PASS
  tampered_response_refused: PASS
  unknown_key_refused: PASS
  wrong_signer_refused: PASS
  repository_default_fails_closed: true
  production_trust_boundary: UNPROVEN
  canary_safe: false
registration:
  ownership_fail_closed: true
  eie_owner: eie
  converge_routable: PASS
validation:
  lint: PASS
  format: PASS
  typecheck: PASS
  tests: PASS
  test_count: 389
  installed_package: PASS
  contracts: PASS
  sdk_pin: PASS
  sdk_worker_runtime: PASS
  signed_round_trip: PASS
  real_eie: NOT_RUN
  deployed_gate: NOT_RUN
  make_pr: NOT_AVAILABLE
blocking_defects: []
external_release_blockers:
  - production ingress trust boundary unproven (deployment evidence required)
  - no live Odoo -> Gate -> EIE runtime proof
  - Gate_SDK cryptography<45 ceiling and open dependency-audit finding
  - EIE and Odoo not yet on bfe6642
verdict:
  local: GO
  routing_contract: GO
  transport_closure: GO
  runtime: GO for the SDK rail, PROOF_PENDING for live processes
  merge: APPROVE
  canary: NO_GO
next_move: >
  Update EIE and Odoo to the same exact Gate_SDK head (bfe6642), then execute
  the four-repository real-runtime release-set proof.
```
