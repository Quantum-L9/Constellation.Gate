# FINAL_FINDINGS — Constellation.Gate routing closure

# Executive Verdict

**Local: GO. Routing contract: GO. Runtime: PROOF_PENDING. Merge: APPROVE.
Release set: PENDING (EIE SDK pin).**

Gate is the sole routing authority, domain payloads are opaque, and the packets
Gate emits now pass the SDK's own worker-side validation. Seven defects were
closed, four of which were silently breaking production behavior:

1. **Every make-based gate was inert.** The `Makefile` ended with stray markdown
   (`------------`, a ` ```yaml ` fence). `make lint`, `make typecheck` and
   `make test` all died at `Makefile:33: *** missing separator`. Any CI or
   contributor invoking them got a hard failure, not a check.
2. **Every dispatch packet Gate emitted was rejectable by any SDK worker.** The
   pinned SDK's `derive()` appended the *parent's* `hop_trace` to each child.
   Those hops carry the parent's `packet_id`, so `validate_hop_trace` raises
   `hop packet_id does not match packet header packet_id`. This was invisible
   locally because no test ran the SDK's inbound validation on a dispatched
   packet.
3. **Cross-tenant idempotency collision.** The cache key was the caller-chosen
   `header.idempotency_key` alone. Two tenants picking `"req-1"` were served
   each other's response packets.
4. **The advertised replay window did not exist.** Expiry lived in a `prune()`
   nothing called, so a `packet_id` was rejected forever and the guard's dict
   grew without bound.

Plus: blind whole-operation retry of `converge`, a deadline that never reached
the network client, staging/prod defaulting to unauthenticated ingress, and a
per-node admission gate that was constructed and never wired.

One item is externally blocked and correctly classified rather than faked:
Gate→worker transport is Gate-local because **Gate_SDK exposes no
Gate-authorized worker transport primitive**. See `GATE_SDK_REQUIRED_DELTA.md`.

# Repository / Branch / Candidate HEAD

| Field | Value |
|---|---|
| Repository | `Quantum-L9/Constellation.Gate` |
| Branch | `claude/gate-routing-sdk-integration-tk6i2p` |
| Starting HEAD | `545eda4` (identical to `origin/main`) |
| Candidate HEAD | `4e4c733f83035fa610fddb73e6a00ed586659d6d` (+ error-mapping commit) |
| Python | 3.12.3 (repo requires >=3.12; container default `python3` is 3.11) |
| Gate version | 1.0.0 |
| Open local changes at start | none (only untracked `.claude/`) |
| Deployment manifests found | `deploy/docker-compose.yml` only — `L9_ENVIRONMENT: local` |

# Gate_SDK Version

| Field | Value |
|---|---|
| Previous pin | `a770e8531dc1c59ce01e1dbb0f4162785d9dda89` |
| **New pin** | `d09fe58a6cd68ef8aa883896c68badc95f96e090` (SDK `main` HEAD) |
| Commits spanned | 17 |
| SDK `FINAL_FINDINGS.md` | **absent** on SDK main |
| SDK `PR_FINDINGS_BRIEF.md` | **absent** on SDK main |
| SDK branch `claude/gate-routing-sdk-integration-tk6i2p` | exists, **0 commits ahead of `main`** |

There is no separate in-flight SDK candidate: the concurrent SDK branch is
identical to `main`, and neither findings artifact exists. `d09fe58` is
therefore the audited head, and it was inspected before adoption.

**Why the bump was mandatory, not opportunistic.** SDK `1d52369` fixes
`derive()` hop inheritance (defect 2 above). Under the old pin, Gate could not
emit a packet an SDK worker would accept.

**Wire compatibility with EIE's older pin.** `1d52369` also made
`transport_hash` UTC-stable: old code did `value.astimezone()` (local tz), new
does `value.astimezone(UTC)`. Verified on this host — identical output on a UTC
host, divergent only on a non-UTC host. Containerized deployments are
unaffected; the derive fix is one-directional (new-SDK Gate emits packets both
old- and new-SDK workers accept), so bumping Gate alone is safe and strictly
better.

# Routing Authority

`client → Gate`, `node → Gate`, `Gate → worker` preserved. Rejected shapes are
covered by `tests/architecture/` (`test_gate_only_routing`,
`test_no_direct_node_to_node`, `test_gate_dispatch_authority`,
`test_orchestrator_via_gate`) plus new negative tests in
`tests/integration/test_ingress_security_negative.py`:

- a node-originated packet targeting a peer is rejected at ingress;
- a caller forging `origin_kind="gate"` is rejected by
  `validate_gate_dispatch_policy` (source must equal the local Gate node);
- a dispatch packet not declaring `resolved_by_gate=true` is rejected.

Registry/routing knowledge stayed in Gate. Nothing was moved into SDK consumers.

# Action Ownership Matrix

| Action | Required owner | Registered node | Owner metadata | Healthy | Resolver |
|---|---|---|---|---|---|
| `converge` | `eie` | `enrichment-engine` | `owner: eie` | yes | resolves ✔ |
| `graph-inference-result` | `eie` | `enrichment-engine` | `owner: eie` | yes | resolves ✔ |
| `enrich`, `enrich-and-sync` | (none) | `enrichment-engine` | `owner: eie` | yes | resolves ✔ |
| `match`, `sync`, `outcomes` | `ceg` | not registered | — | — | not routable |

Cross-checked verbatim against EIE `app/services/gate_registration.py` at its
current HEAD (`cfda450`): `NODE_NAME="enrichment-engine"`,
`SUPPORTED_ACTIONS=["converge","graph-inference-result","enrich","enrich-and-sync"]`,
`HEALTH_ENDPOINT="/api/v1/health"`, `metadata={"owner":"eie",...}`.

Fail-closed proven: a non-`eie` node claiming `converge` is rejected; an
unowned node claiming a canonical action is rejected; cross-owner collision on a
shared action is rejected; **replicas of the same owner are allowed**.
`tests/routing/test_action_ownership_matrix.py`.

No stale or wrong-owner registration found. Note `config/node_registry.yaml`
still ships legacy `enrich` / `cognitive_engine_graphs` entries; these are
inert (the registry is empty at startup unless explicitly loaded) and do not
collide, because neither carries owner metadata.

# Domain Payload Opacity

**Clean.** No application-domain field is read anywhere in Gate production code.
The only repository-wide hit was a docstring in `config/workflows.yaml`.

Two complementary guards now hold it (`tests/architecture/test_domain_payload_opacity.py`):

- a static AST scan of every `src/constellation_gate/**.py` for domain
  identifiers *including string literals* (a payload key is read as a string).
  Verified against a planted violation — it fails as intended;
- adversarial round-trip proof over six payload shapes (deep nesting, unicode
  and the `\x1f` namespace separator, empty keys, extreme numbers, nulls,
  and a payload deliberately named `entity`/`writeback`/`odoo`), asserting
  `child.payload == ingress.payload` **and** `payload_hash` equality through
  ingress → observation hop → derive → the packet actually handed to transport;
- plus a hostile-payload test proving payload keys named `action`, `tenant`, and
  `destination_node` change nothing about routing.

Gate also does not mutate the caller's payload object in place.

# Gate→Worker Transport State

**`worker_transport_cleanup: BLOCKED_EXTERNAL_SDK_CAPABILITY`**

`GateClient` is structurally node→Gate: `assert_node_origin_packet` requires
`origin_kind == "node"` (a Gate dispatch packet is `"gate"`) and
`assert_gate_only_destination` requires `destination_node == "gate"` (a dispatch
packet targets a worker). It cannot carry Gate's side of the hop, and there is
no lower-level packet-send helper in the SDK.

Responsibility inventory:

| Responsibility | Owner now |
|---|---|
| resolution, derivation, dispatch authorization, deadline | `GATE_ROUTING_OWNED` (`routing/dispatch.py`) |
| serialization, POST, network timeout, status mapping, JSON decode, typed errors | `EXTERNAL_SDK_CAPABILITY_GAP` → held in `routing/worker_transport.py` |
| outbound/inbound packet validation, signing, derivation algorithm | `GATE_SDK_TRANSPORT_OWNED` (unchanged, not reimplemented) |

Gate did **not** create a permanent parallel client abstraction. It has one
narrow adapter with a single function whose signature deliberately matches the
proposed SDK API, plus the typed error hierarchy the SDK should eventually own.
`tests/architecture/test_worker_transport_seam.py` fails the build if a second
HTTP sender appears, if `Dispatcher` regains `raise_for_status`/`.json()`, or if
the seam stops pointing at the required delta.

# Packet Derivation / Hop State

Proven in `tests/integration/test_cross_repo_converge_round_trip.py` against the
SDK's real `validate_transport_packet`, not a hand-rolled stub:

new `packet_id` ✔ · `parent_id` ✔ · `root_id` preserved ✔ · `generation + 1` ✔ ·
`causation_id` ✔ · `correlation_id` preserved ✔ · source `gate` ✔ · destination
worker ✔ · `reply_to` gate ✔ · payload preserved ✔ · tenant immutable ✔ ·
**parent-bound hops not inherited** ✔ · dispatch hop bound to the child ✔ ·
transport hash valid ✔ · worker validation passes ✔.

No SDK derivation algorithm was duplicated in Gate.

# Retry State

| Path | Gate attempts |
|---|---|
| `converge` | **1** — permanently, cannot be configured otherwise |
| any ordinary action | **1** |
| ordinary action *with* an idempotency key | **1** (a key alone is not sufficient) |
| action declared replay-safe *without* a key | **1** |
| action declared replay-safe *with* a key | `retry_policy.max_attempts` |

`RetryPolicy` was **not** deleted; it is invoked explicitly with a per-packet
attempt budget from `ReplaySafetyPolicy`, never as an implicit global wrapper.
Default posture: nothing is replay-safe. `converge` is in
`NEVER_REPLAY_SAFE_ACTIONS`, so a misconfiguration raises `ReplaySafetyError` at
construction rather than silently enabling replay — EIE owns provider retries
there. Retry backoff consumes the packet deadline.

Rationale recorded in code: a worker timeout means "no answer arrived", never
"no work happened".

# Deadline State

**One monotonic deadline.** `PacketDeadline` is created once, immediately after
ingress validation, from `timeout_policy.resolve(packet)`, and is never
refreshed. Downstream budget is `min(remaining, registered node cap)`.

The previous code passed `target.timeout_ms` — a **fresh, full** per-node
timeout — to the HTTP client on *every* attempt, while `asyncio.wait_for` only
bounded the awaiting coroutine. `tests/services/test_execute_service_deadline.py`
asserts on the timeout the network client actually receives, not on `wait_for`:

- 28s spent of a 30s budget, 30s node cap → worker gets **2.0s**;
- 5s node cap under a 30s budget → worker gets **5.0s** (cap still binds);
- exhausted budget → **no worker call is made at all**;
- three dispatches under one deadline → `20.0 → 12.0 → 4.0`.

Workflow steps share the same deadline and a step's declared `timeout_ms` is
clamped to what the packet has left.

# Idempotency State

Namespace: **`tenant.org_id` + normalized `action` + `header.idempotency_key`**,
joined by `\x1f`. Tenant is read from the canonical SDK `TransportPacket.tenant`
context, never from the opaque payload (a payload-derived tenant would be
attacker-controlled).

Proven: cross-tenant isolation, cross-action isolation, same-triple cache hit
across distinct `packet_id`s, unkeyed requests never cached, case-insensitivity.

**Process-local. Not durable. Not represented as durable.**

**Cache result safety (decided contract):** a replay returns the *original*
canonical response packet verbatim — same `packet_id`, `correlation_id`,
`causation_id`, and lineage. Re-deriving a fresh response would fabricate a hop
chain and a generation bump for work that never ran, and would name the replay
packet as parent of a result it did not produce. Callers correlate on
`header.correlation_id`, which the original response carries. Asserted, not
assumed, in `test_cached_replay_returns_the_original_canonical_response`.

# Replay State

Expiry now happens **inside `check_and_record`** on the hot path. Correctness no
longer depends on an operator calling `prune()` (`prune()` is retained for
diagnostics). State is bounded by a hard `max_entries` ceiling with oldest-first
eviction, using an insertion-ordered map so expiry stops at the first live entry.
Clock is injectable, so window behavior is tested deterministically without
sleeping.

Proven: first occurrence accepted · duplicate inside window rejected · **same
packet_id accepted again after the window** · aged entries retired by an ordinary
call · 1000 unique packets under a 100-entry ceiling stay bounded · oldest
evicted first · `ReplayDetectedError` remains a `ValueError` for existing
handlers.

# Ingress Security / Trust Boundary

```
production_trust_boundary: UNPROVEN (from repository evidence)
  packet_signatures:      available, previously OFF by default in every env
  authenticated_network:  no manifest, mesh config, or ingress config in-repo
  public_reachability:    undetermined — no staging/prod manifest exists
  evidence:               deploy/docker-compose.yml only, L9_ENVIRONMENT=local,
                          L9_REQUIRE_SIGNATURE=false
```

No staging or production deployment manifest exists in this repository, so the
real boundary **cannot be established from repository evidence**. No
infrastructure was invented.

What *was* fixed: `staging` and `prod` now **fail closed at startup** unless one
boundary is explicitly named — `L9_REQUIRE_SIGNATURE=true` *with* key material
(require_signature with no keys would reject every packet, so that is rejected
too), or `L9_TRUSTED_NETWORK_INGRESS=true` as a deliberate operator assertion.
`dev_mode` is rejected outright in those environments. `local`/`dev`/`test` are
unchanged. Packet validation stays on as defense in depth either way — the
assertion records which mechanism is authoritative, it relaxes nothing.

Gate can no longer silently run production unauthenticated. Whether the
deployment satisfies the boundary it now must declare is an operator fact this
repository cannot verify.

# Registration State

Generic and unchanged in shape. `NodeRegistration` field set is asserted exactly,
so an EIE-specific field cannot be added without failing a test. Gate accepts the
live EIE payload as-is, including `metadata.owner`, a non-default
`health_endpoint`, and version/type metadata. Ownership enforcement is
fail-closed.

# EIE Routability

`GET /v1/ready` added, distinct from `/v1/health` (which stays a pure liveness
probe — redefining it would take Gate out of rotation whenever a worker blips).
Readiness resolves through `registry.resolve_action`, the same call the resolver
makes, so it cannot drift from real routing. Returns 503 when a declared required
action is not routable, and names the reason.

`converge` routability is proven against the exact EIE registration shape:
registered ✔ · `owner=eie` ✔ · advertised ✔ · ownership valid ✔ · healthy ✔ ·
resolver selects it ✔ · dispatch probe passes against an SDK-validating worker ✔.
Against a **live EIE process: NOT_RUN** (no EIE instance in this environment).

# Workflow State

Audited separately. No domain translation; no deadline reset (steps share the one
budget, and a step's declared `timeout_ms` is clamped to the remainder); no
direct worker HTTP (every step goes through the Gate-owned dispatcher); packet
derivation is SDK-owned; retry is governed by the same replay-safety policy as
ordinary dispatch. Workflows were not broken to fix ordinary dispatch.

# Dependency / Installability Evidence

- `pip install -e ".[dev]"` — PASS (Python 3.12.3 venv)
- clean wheel build (`python -m build --wheel`) — PASS
- clean-venv install of the built wheel — PASS; app constructs, all 11 routes
  present including `/v1/ready`, readiness resolves `converge`
- exact candidate SDK resolved from git in the clean venv, derive-hop fix present

# Cross-Repository Runtime Evidence

```
sdk_worker_runtime_fixture: PASS
real_eie_runtime:           NOT_RUN
deployed_gate:              NOT_RUN
```

`tests/integration/test_cross_repo_converge_round_trip.py` drives an
Odoo-shaped root packet (nested `entity`, `writeback.odoo`, `requested_fields`)
through Gate ingress → `converge`/`owner=eie` → resolver → Gate-authored child →
worker transport → **the SDK's own `validate_transport_packet`** at the worker
end → canonical response → Gate response validation. The worker end runs real SDK
validation, so this proves the emitted packet is one a real SDK node accepts — but
it is a fixture, not a live EIE process, and is not claimed as one.

# Tests Actually Executed

| Command | Result |
|---|---|
| `pip install -e ".[dev]"` | PASS |
| `make lint` (`ruff check src tests`) | PASS |
| `make typecheck` (`mypy src`, strict, 70 files) | PASS |
| `make contracts` | PASS |
| `make test-unit` | PASS — 140 |
| `make test-integration` | PASS — 24 |
| full `pytest -q` | PASS — **292** (from 181 at baseline) |
| `python -m build --wheel` | PASS |
| clean-venv installed-package smoke | PASS |

New coverage: deadline (10) · replay safety (8) · replay window (9) ·
idempotency namespace unit (7) + service (5) · retry safety (7) · transport
deadline (4) · domain opacity (8) · transport seam (4) · ingress trust (10) ·
readiness (5) · ownership matrix (8) · security negatives (14) · cross-repo
round trip (3) · error mapping (2) · DLQ bound (1).

No test was skipped, weakened, or deleted to reach green.

**Two pre-existing tests asserted defective behavior and were corrected to the
real contract, not worked around:**

- `tests/resilience/test_idempotency.py` wrote to the raw key `"abc"`, encoding
  the flat key space that caused the cross-tenant collision. Rewritten against
  `build_idempotency_scope`, with the collision cases added.
- `tests/architecture/test_lineage_reentry.py` asserted `len(hop_trace) == 2` on
  the dispatched child — that second hop was the parent's ingress hop, bound to
  the parent's `packet_id`, i.e. exactly the thing that made the packet
  SDK-invalid. Corrected to one child-bound dispatch hop, **and** hardened with
  a real `validate_transport_packet` call so the class of bug cannot recur
  silently.

Twelve test doubles were updated to match the real `dispatch`/`execute`
signatures (an optional keyword-only `deadline`); a double that does not match
the signature it stands in for has stopped being a double.

# Remaining Blocking Defects

None in Gate.

# Remaining Non-Blocking Defects

1. `resilience/failure_policy.py` (`FailurePolicy`) is exported and tested but
   used by no production code. Dead code; it classifies `TimeoutError` as
   retryable, which is now the opposite of Gate's posture — a future caller
   wiring it would silently reopen the blind-retry hole. Recommend deleting it.
2. `config/node_registry.yaml` ships legacy `enrich` / `cognitive_engine_graphs`
   entries with URLs that do not correspond to any current deployment. Inert (not
   loaded at startup) and non-colliding, but stale.
3. `config/workflows.yaml` references an `enrich` node that is not the canonical
   `eie` registration; the shipped `full_pipeline` workflow would not resolve in a
   real deployment. Workflows are disabled unless `GATE_WORKFLOW_CONFIG_PATH` is
   set, so this is latent.
4. `deploy/docker-compose.yml` mounts `../.env.example` as its `env_file` — an
   example file is not a deployment secret source.
5. The dead-letter queue is process-local and now explicitly documented as
   observability-only; it was also unbounded (a full packet dump per entry,
   filling fastest during exactly the outage that produces them) and is now
   capped at 1000 with oldest-first eviction.

# External SDK Blockers

1. **No Gate-authorized worker transport primitive** in Gate_SDK. Full required
   API in `GATE_SDK_REQUIRED_DELTA.md` §2. Gate's adapter is shaped for a
   one-function swap; `Dispatcher` will not change.
2. **EIE still pins `a770e853`** (`pyproject.toml`, `requirements-ci.txt`) — the
   commit with the derive hop bug and the local-TZ hash. Harmless on a UTC host
   (verified byte-identical), but the guarantee should not rest on host timezone.
   EIE should move to `d09fe58`.

# Deferred Work

`durable_distributed_gate_idempotency` · `durable_dead_letter_infrastructure` ·
`queue_redesign` · `registry_database_redesign` · `generalized_workflow_redesign`
· `TransportSecurity_hash_envelope_redesign` — all untouched, as scoped.

# Scope Drift Audit

No domain translation, no direct application→worker path, no node→node path, no
provider retry logic, no EIE domain logic, no Odoo writeback logic, no new
transport protocol. Gate was not redesigned.

Two changes go slightly beyond the literal required list and are named rather
than buried:

- **Dispatcher wiring** (`api/dependencies.py`): the pooled HTTP client and the
  per-node concurrency limiter were constructed at startup and never passed to
  the `Dispatcher`. The limiter is described in the dispatcher's own comment as
  "the authoritative admission gate" and it never ran; every dispatch opened and
  discarded its own client. In scope because the deadline must reach the *actual*
  transport, and the actual transport was not the one the app had built.
- **Worker-transport error mapping** (`api/errors.py`): the new typed errors fell
  through to `500 internal_error`, reporting an upstream worker failure as a Gate
  bug and sending an operator to the wrong service. Now `502` (`504` for
  timeouts). This completes §18's "preserve actionable cause chains".

# Merge Recommendation

**APPROVE.** Lint, strict typecheck, contracts, 292 tests, clean build and
clean-venv install all pass. The two externally blocked items are classified,
not faked, and the required SDK delta is written down precisely enough to
implement.

# Release-Set Recommendation

**PENDING.** Gate may merge independently. Before the release set closes:

1. EIE moves its SDK pin to `d09fe58` (removes the host-timezone dependency);
2. an operator names the staging/prod ingress trust boundary — Gate now refuses
   to start without one, which is the point;
3. `L9_REQUIRED_READY_ACTIONS=converge` is set so `/v1/ready` gates the canary;
4. a live Gate↔EIE round trip replaces `sdk_worker_runtime_fixture`.

# Next Straight-Line Move

Open the Gate_SDK issue from `GATE_SDK_REQUIRED_DELTA.md` §2 and bump EIE's SDK
pin to `d09fe58` — both are small, unblock the last classified gap, and are
prerequisites for the live round trip.

# Machine-Readable Summary

```yaml
repository: Quantum-L9/Constellation.Gate
branch: claude/gate-routing-sdk-integration-tk6i2p
candidate_head: "4e4c733f83035fa610fddb73e6a00ed586659d6d"
gate_sdk:
  pinned_sha: "d09fe58a6cd68ef8aa883896c68badc95f96e090"
  previous_pinned_sha: "a770e8531dc1c59ce01e1dbb0f4162785d9dda89"
  installed_package: PASS
  worker_transport_sdk_owned: false
  external_capability_gap: "no Gate-authorized worker-packet transport primitive; GateClient is structurally node->Gate (asserts origin_kind=='node' and a Gate-only destination). See GATE_SDK_REQUIRED_DELTA.md"
routing:
  sole_authority: true
  direct_peer_routing: false
  converge_owner: eie
  domain_payload_opaque: true
retry:
  generic_whole_operation_retry: false
  converge_gate_attempts: 1
  replay_requires_idempotency: true
  retry_requires_explicit_safety: true
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
  packet_validation: true
  canary_safe: false
registration:
  ownership_fail_closed: true
  eie_owner: eie
  converge_routable: PASS
validation:
  lint: PASS
  typecheck: PASS
  unit: PASS
  integration: PASS
  installed_package: PASS
  cross_repo: PASS
  make_pr: PENDING
blocking_defects: []
non_blocking_defects:
  - "FailurePolicy is dead code that classifies TimeoutError as retryable, contradicting Gate's posture"
  - "config/node_registry.yaml ships stale legacy node entries"
  - "config/workflows.yaml full_pipeline references a non-canonical enrich node"
  - "deploy/docker-compose.yml uses .env.example as its env_file"
external_blockers:
  - "Gate_SDK lacks a Gate-authorized worker transport primitive (GATE_SDK_REQUIRED_DELTA.md)"
  - "Enrichment.Inference.Engine still pins Gate_SDK a770e853 (derive hop bug + local-TZ hash)"
verdict:
  local: GO
  routing_contract: GO
  runtime: PROOF_PENDING
  merge: APPROVE
  release_set: PENDING
next_move: "Open the Gate_SDK worker-transport issue from GATE_SDK_REQUIRED_DELTA.md and bump EIE's SDK pin to d09fe58."
```
