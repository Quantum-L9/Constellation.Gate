# CONSTELLATION.GATE SDK-ADOPTION FINDINGS BRIEF

HEAD: 3b5c959568e904ded02d3243d9efce24d7257e34
BRANCH: claude/gate-sdk-transport-adoption-ay1sc4
BASE: origin/main @ 545eda4259121dbce85c084385f68d00632981d7
CONTINUES: claude/gate-routing-sdk-transport-4btf4g @ 56c9cff (not origin/main —
  that branch carried ~3,900 lines of audited work that restarting would discard)

SDK SHA: bfe6642062a85a720ad8c25e96446d4df1c299ac
  source: Quantum-L9/Gate_SDK PR #40 (branch claude/gate-sdk-transport-closure-u2klcf)
  merged to SDK main: NO — the pin targets an unmerged PR head, deliberately
  provenance: installed dist direct_url.json records that exact commit_id

TRANSPORT:
  worker_transport_sdk_owned: true
  direct_httpx_remaining: none (dispatch.py imports httpx for a type only)
  manual_response_packet_parsing: none
  shadow_transport_allowlist: [] (empty; module deleted, absence asserted)
  api: GateDispatchTransport.send_gate_authored_packet
  network_attempts_per_dispatch: 1
  pooled_client_reused: true (SDK never closes a client it did not create)

DEADLINE (INV-GATE-DOWNSTREAM-DEADLINE-IDENTITY):
  root:   30,000 ms
  child:   2,000 ms   (min(remaining 2s, node cap 25s))
  socket:      2.0 s  (SDK derives it from the child's header.timeout_ms)
  worker:      2.0 s  (runtime bounds its handler with the same field)
  previously the child advertised 30,000 ms while Gate waited 2s

ROUTING:
  Gate_still_selects_worker: yes (registry, health, capacity, backpressure all Gate)
  sdk_may_resolve_or_failover: no
  domain_payload_opaque: yes
  converge_owner: eie
  converge_routable: PASS (readiness + delivery asserted against one registry)

SECURITY:
  gate_authority_validation: PASS (6 negatives, each with ZERO network requests)
  signed_round_trip: PASS (both directions, plus 4 forgery cases)
  repository_default_fails_closed: true
  production_trust_boundary: UNPROVEN
  canary_safe: false

PROVEN:
  - Gate decides where; Gate_SDK performs every canonical worker hop
  - routing/worker_transport.py deleted, not deprecated; ratchet at zero
  - one deadline across child header, socket, and worker handler
  - exactly one network attempt; no hidden SDK retry
  - typed SDK failures drive routing state; only WorkerConnectionError marks a
    node unhealthy, so a slow worker is no longer ejected from routing
  - GateDispatchAuthorityError / ConfigurationError map to 500, never 400 — both
    subclass ValueError and would otherwise blame the caller for a Gate bug
  - the SDK's chained httpx cause survives Gate's re-raise
  - a node cannot buy peer transport by knowing a worker's URL
  - payload, tenant, correlation, idempotency, and root lineage cross unchanged
  - every dispatch test now runs against the real SDK worker runtime, not a fake

BLOCKERS:
  - none in this repository

EXTERNAL RELEASE DEBT:
  - production ingress trust boundary unproven (needs deployment evidence)
  - no live Odoo -> Gate -> EIE runtime proof (real_eie: NOT_RUN)
  - Gate_SDK cryptography>=43,<45 ceiling + open dependency-audit finding;
    explicitly NOT resolved here (not by loosening the SDK bound, changing Odoo
    pyOpenSSL, or suppressing the finding)
  - EIE and Odoo still pinned to older SDK commits

TESTS:
  - command: ruff check src tests
    result: PASS
  - command: ruff format --check src tests scripts
    result: PASS (175 files)
  - command: mypy src
    result: PASS (69 files)
  - command: pytest -q
    result: PASS — 389 passed (was 339 before this pass)
  - command: python scripts/validate_contracts.py
    result: PASS
  - command: python scripts/validate_sdk_pin.py
    result: PASS (bfe6642…)
  - command: make pr
    result: PASS — validation gate only (lint + typecheck + test); this repo's
             pr target does not push, tag, or open a pull request
  - command: uv pip install -e ./constellation-gate[dev] (clean 3.12 venv)
    result: PASS, direct_url.json commit_id == bfe6642…
  - mutation: add a production module that POSTs /v1/execute and parses the reply
    result: 2 architecture drift guards FAIL (guards are non-vacuous)
  - mutation: remove timeout_ms= from the child derivation
    result: 4 deadline tests FAIL (invariant is non-vacuous)

REMOTE PR: https://github.com/Quantum-L9/Constellation.Gate/pull/14
  base: claude/gate-routing-sdk-transport-4btf4g (STACKED on PR #13, merge bottom-up)
  NOTE: an earlier brief recorded "the Gate functional branch has no remote PR".
  That was wrong — PR #13 is open for 4btf4g. This branch stacks on it rather
  than opening a sibling against main, and 6e6cc24 was merged in (both branches
  had independently added .claude/ to .gitignore; the parent's wording was kept).

STALE FINDINGS RETIRED (do not carry forward):
  - "gate_authorized_worker_packet_transport missing from Gate_SDK" — shipped
  - "worker_transport_sdk_owned: false" — now true
  - "external_capability_gap: gate_authorized_worker_packet_transport" — null
  - "next_move: land send_gate_authored_packet" — done and consumed
  - Gate owns _post_dispatch_packet / post_worker_packet — module deleted

NOTE ON THE SDK'S OWN VERDICT:
  Gate_SDK PR #40 reports release_set: GO. That cannot mean the four-repository
  production release set: at the time it was written no consumer had adopted
  bfe6642, no real Odoo -> Gate -> EIE run had happened, and Gate's ingress trust
  boundary was unproven. This PR closes the first of those three, for Gate only.

NEXT STRAIGHT_LINE_MOVE:
  Bring EIE and Odoo onto this same SDK SHA and run the real
  Odoo -> Gate -> EIE -> PostgreSQL -> Gate -> Odoo release-set rail.
    EIE:  pin bfe6642, delete the bespoke Gate registration in favour of the
          SDK's typed register_node() with metadata.owner, re-run the
          PostgreSQL/domain gates, then a real Gate round trip. Its "SDK cannot
          send metadata.owner" finding is stale, as is its claim that Odoo does
          not supply domain idempotency.
    Odoo: pin the same SDK, replace create_transport_packet + send_to_gate with
          GateClient.execute(), drop the now-unnecessary raw httpx and legacy
          error handling, run real Odoo 19. Its "Gate_SDK has no execute()"
          finding is stale.
