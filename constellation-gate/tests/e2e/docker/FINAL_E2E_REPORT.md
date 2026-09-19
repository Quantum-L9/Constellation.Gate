# Constellation release-set system E2E — Docker rail

**Overall result: PASS (system transport E2E), with two environment accommodations and one supply-chain finding.**

This is not an unqualified "the product works" claim. It is: *these three
revisions, built as real images from their own Dockerfiles, start with their
real entrypoints, register themselves with a real Gate, and interoperate over
real TCP through Gate under mandatory signing — and the architecture fails
correctly when attacked.* The one business path that requires a paid external
provider was not exercised, and is named as out of scope below rather than
simulated.

Last run: `20260919T164952Z` — 17/17 checks PASS, reproduced across four
consecutive clean-slate executions (the last with a Gate image rebuilt from
`build_images.sh` alone and freshly generated credentials).

---

## 1. Revision set

| Repository | HEAD | Branch | Product code changed |
|---|---|---|---|
| Quantum-L9/Constellation.Gate | `fc1b3d8b046d3f2e6fb8b8a8fcb0ab64708e2b41` | `claude/constellation-e2e-docker-ixctez` | none |
| Quantum-L9/Enrichment.Inference.Engine | `843db96f4d00f49c95f083039459bbbcc42f82e2` | `claude/constellation-e2e-docker-ixctez` | none |
| Quantum-L9/Cognitive.Engine.Graphs | `dfbdad2d7e78e819fb2461ded7c8b128bbdcb1f0` | `claude/constellation-e2e-docker-ixctez` | none |

**No product code in any repository was modified.** The E2E required no fix to
make it pass. Working trees were clean at campaign start; the only additions
are this harness (`constellation-gate/tests/e2e/docker/`) and gitignored
evidence under `constellation-gate/.l9/runtime/docker-e2e/`.

## 2. Image set

| Image | Built from | Image ID |
|---|---|---|
| `l9e2e/gate:local` | `constellation-gate/Dockerfile` | `sha256:5c79f3dc4bed…` |
| `l9e2e/eie:local` | `Enrichment.Inference.Engine/Dockerfile` | `sha256:4a36c5889c4c…` |
| `l9e2e/ceg:local` | `Cognitive.Engine.Graphs/Dockerfile` | `sha256:33def0176fd7…` |

Supporting: `neo4j:5-enterprise`, `redis:7-alpine`, `postgres:16-alpine`.

## 3. SDK provenance — resolved from the running containers

Read from each image's installed `dist-info/direct_url.json`, not from lockfiles.

| Node | SDK version | Installed commit | Declared as | Source of truth |
|---|---|---|---|---|
| gate | 1.1.0 | `2b2f53a28a59bbfb2fa45f5eac32b722d802209a` | `requirements.lock` archive URL | vendoring receipt |
| eie | 1.0.1 | `69c6c67060b08440734a61473c03663423709964` | pinned SHA | container dist-info |
| ceg | 1.1.0 | `e9f829f982110be13752da8f18c7a9692e8ed908` | **`@v1` — a mutable tag** | container dist-info |

**Three different commits across three images.** Resolved at source level:

- EIE (`69c6c67`) and CEG (`e9f829f`) have **byte-identical `src/` trees**
  (`src_tree=4785dc8d…`) despite different version strings. They are
  interchangeable in code; only the metadata differs.
- Gate's image (`2b2f53a2`, `src_tree=cfe9eb0c…`) **differs by 31 lines in
  `src/constellation_node_sdk/gate/config.py`**. That commit hardcodes
  `verifying_keys={}` in `get_gate_client_config_from_env()`; the fix that
  loads `L9_VERIFYING_KEYS_JSON` from the environment lands in `69c6c67`
  and `e9f829f`.

### Findings

1. **Gate's container SDK is older than Gate's own CI SDK.** `pyproject.toml`
   pins `69c6c67` (what CI installs); `requirements.lock` pins `2b2f53a2`
   (what the image installs). Production runs code CI does not test.
   Impact is limited — Gate's *ingress* verification reads
   `L9_VERIFYING_KEYS_JSON` through its own `GateSettings`, not the SDK env
   helper — but any Gate-side use of `get_gate_client_config_from_env()`
   would silently get an empty verifying-key map.
2. **CEG pins a mutable ref.** `requirements.txt` and `pyproject.toml` use
   `@v1`. Today `v1` → `e9f829f`; it can move without any repo changing.
   `poetry.lock` records the resolved SHA, but the dev `Dockerfile` uses
   `pip install -r requirements.txt` and resolves `@v1` live, so dev and prod
   images can diverge.
3. **Gate's `pyproject.toml` comment is factually wrong** where it states EIE
   and CEG pin the same commit — CEG pins `v1`, not `69c6c67`.

Owning declarations: `constellation-gate/requirements.lock:10`,
`constellation-gate/pyproject.toml:19`, `Cognitive.Engine.Graphs/requirements.txt:21`,
`Cognitive.Engine.Graphs/pyproject.toml:27`.

## 4. Topology actually run

```
                        control_net
                             │
                        ┌────┴────┐
        gate_eie_net ───│  gate   │─── gate_ceg_net
              │         └─────────┘          │
     ┌────────┴────────┐            ┌────────┴────────┐
     │enrichment-engine│            │      graph      │
     └────────┬────────┘            └────────┬────────┘
         eie_data_net                   ceg_data_net
        redis + postgres                    neo4j
```

Five Docker networks. Gate is the only service on both transport networks.
`enrichment-engine` and `graph` share **no** network, so peer isolation is
structural, not conventional — each resolves `gate` on a *different* interface
(172.22.0.2 vs 172.18.0.2) and cannot resolve the other at all.

Registered addresses in Gate's live registry (which starts **empty** — no
static YAML seed):

- `enrichment-engine` → `http://enrichment-engine:8000`, actions
  `converge, graph-inference-result, enrich, enrich-and-sync`, owner `eie`
- `graph` → `http://graph:8000`, actions `match, sync, outcomes, resolve`

## 5. Scenarios executed

### Positive

| ID | Proof | Evidence |
|---|---|---|
| REG | Both nodes self-register with the live Gate | `gate_registry.json` |
| P1 | signed client → Gate → **EIE** (`graph-inference-result`) | `{"status":"accepted","targets_queued":1}`, signed response |
| P2 | signed client → Gate → **CEG** (`sync`) | `{"status":"success","synced_count":1}` + Neo4j row |
| P3 | signed client → Gate → **CEG** (`match`) | real `candidates`/`scoring_meta` response |
| P4 | replay of an identical signed packet | 1st `200` response, 2nd `400 replay detected`, **one** row written |
| P5 | **CEG → Gate → EIE**, via CEG's own `engine.gate_egress` | `packet_type: response`; EIE handler genuinely ran (`inference_version v2.2.0`, 127 ms) |
| P6 | **EIE → Gate → CEG**, via EIE's own `PacketRouter.notify_graph_sync` | `{"status":"success","synced_count":1}` + Neo4j row `enriched_by=enrichment-engine` |
| P7 | recovery after worker restart | re-registered healthy in ~10 s, `sync` succeeds again |

### Adversarial

| ID | Attack | Actual behaviour |
|---|---|---|
| N1 | valid packet, signature removed | `400 invalid_transport_packet` — *"signature required but not present"* |
| N2 | signature from an unknown key | `400 invalid_transport_packet` — *"invalid transport signature"* |
| N3 | action no node owns | `404 not_found` — *"no node registered for action: graph-query"* (permanent, not 503) |
| N4 | client names a worker to bypass routing | `400` — *"packet destination does not match this node"* |
| N5 | owning worker stopped | `502 worker_transport_failed`, `node: graph`, real `ConnectError`; **no direct-peer fallback**; registry flips `healthy=false` |
| N6 | direct peer reachability | `getent hosts graph` from EIE → exit 2; `getent hosts enrichment-engine` from CEG → exit 2; `gate` resolves from both |

### Data effects verified in Neo4j (`database=plasticos`)

```
facility_id,        tenant,      enriched_by,         marker
"E2E-EIE-EGRESS-1", "plasticos", "enrichment-engine", "eie-to-ceg"
"E2E-F-001",        "plasticos", NULL,                "docker-rail"
"E2E-REPLAY",       "plasticos", NULL,                NULL
```

`E2E-REPLAY` appears exactly once, which is the idempotency proof.

## 6. Scope boundary — what was NOT proven

**EIE's `enrich` business path was not exercised end to end.** `handle_enrich`
requires a reachable Perplexity endpoint (`PERPLEXITY_API_KEY`); with no
provider egress it returns `state: failed`,
`failure_reason: no_valid_responses (APIConnectionError …)`. This is why:

- P5 proves CEG → Gate → EIE **transport** and that EIE's handler executed;
  the business result is unavailable, and is reported as such rather than
  asserted green.
- P6 drives EIE's outbound `sync` through `PacketRouter` directly, because the
  only in-repo trigger (`_persist_and_sync`) runs solely when enrichment
  returns `state == "completed"`.

This is a **system transport E2E**, not a live-provider product E2E. A
`live-provider` profile requiring explicit credentials is the correct home for
the latter and was not run.

Two further gaps found by reading current source, worth recording:

- **`graph-inference-result` has no sender.** EIE advertises and implements it,
  but no CEG code constructs that packet — the action exists in only one
  direction today.
- **CEG's outbound enrichment path has no reachable inbound trigger.**
  `engine/health/api.py` has zero importers and `auto_enrich_via_gate` defaults
  `False`, so no packet arriving at CEG can cause it to call EIE. P5 therefore
  invokes `request_enrichment` directly, exactly as the existing process-rail
  seam harness does.

## 7. Failures encountered and their root causes

Every failure in this campaign was in the harness or the environment. **None
required a product change.**

| Class | Symptom | Root cause | Resolution |
|---|---|---|---|
| ENVIRONMENT | No Docker daemon | Sandbox ships the CLI only | Started `dockerd`; verified overlayfs, custom networks, DNS isolation |
| BUILD | All image builds fail TLS | Egress proxy re-terminates TLS; base images do not trust its CA | CA injected per stage via BuildKit named context — repo Dockerfiles untouched on disk |
| BUILD | Gate build `403` on the SDK | Proxy serves anonymous **git** but returns 403 for `github.com/.../archive/*.tar.gz` | SDK vendored over git at the exact locked SHA; all other lock entries keep `--require-hashes` |
| HARNESS | Neo4j never healthy | Healthcheck referenced a variable not passed into that container | Passed it |
| HARNESS | `GateClient` TypeError | It is not an async context manager | Fixed usage |
| CONFIGURATION | CEG `sync`/`match` returned `ExecutionError` | CEG routes with `database=<domain_id>`; the `plasticos` database did not exist | Created it in the boot sequence |
| **HARNESS (integrity)** | P2/P3 reported PASS while CEG returned `packet_type: failure` | Assertions checked only for absence of an exception | Assertions tightened to require `packet_type == "response"` **and** a success status — the failure was then diagnosed, not hidden |
| **EVIDENCE (integrity)** | Bundle contained all signing keys | `docker compose config` interpolates variables | Added `redact.py`; leak scan is now a gating check (`EVIDENCE_no_secrets`) |

A prediction that did **not** hold, recorded for honesty: reading source
suggested CEG registration would be rejected because `engine/spec.yaml` sets no
`owner` and Gate's `assert_registration_ownership` is fail-closed. In practice
Gate resolved the owner from the node name `graph`, and also accepted the
non-canonical `resolve` action. Empirical beat predicted.

## 8. Environment accommodations (deviations from a pristine build)

Both are transport-level only and are recorded in the bundle:

1. **CA injection** — one `update-ca-certificates` layer per `FROM`, rendered
   by `scripts/ca_inject.py`. Every dependency-resolution and install
   instruction is preserved byte-identically. Images differ from production by
   exactly one added CA certificate per stage.
2. **Gate SDK vendoring** — Gate's lock installs the SDK from a GitHub archive
   URL this session's proxy refuses. The SDK is installed from a `git archive`
   export of **that same commit**, verified by object SHA; pip's tarball hash
   check is replaced by git object verification for that one requirement only.

Neither changes which SDK revision runs, and neither touches product code.

## 9. Files added by this campaign

All under `constellation-gate/`; nothing outside Constellation.Gate was
modified.

```
tests/e2e/docker/compose.yml                  five-network topology
tests/e2e/docker/FINAL_E2E_REPORT.md          this report
tests/e2e/docker/ca/ca-bundle.crt             build-time CA (session-local)
tests/e2e/docker/scripts/build_images.sh      builds from each repo's Dockerfile
tests/e2e/docker/scripts/ca_inject.py         renders the CA-trust layer
tests/e2e/docker/scripts/vendor_gate_sdk.sh   exports Gate's locked SDK commit
tests/e2e/docker/scripts/patch_gate_sdk.py    points Gate's build at that export
tests/e2e/docker/scripts/gen_env.sh           ephemeral per-identity secrets
tests/e2e/docker/scripts/driver.py            signed-packet scenarios
tests/e2e/docker/scripts/eie_egress_probe.py  EIE -> Gate -> CEG
tests/e2e/docker/scripts/ceg_egress_probe.py  CEG -> Gate -> EIE
tests/e2e/docker/scripts/redact.py            evidence redaction + leak scan
tests/e2e/docker/scripts/assert_evidence.py   one verdict from one bundle
tests/e2e/docker/scripts/run_e2e.sh           orchestrator
```

The existing process rail (`tests/e2e/seam/`) is untouched. This is an
additional rail: the process rail proves source interoperability, the Docker
rail additionally proves image construction, dependency resolution, container
entrypoints, Docker DNS, network topology, startup ordering and recovery.

## 10. Reproduction

```bash
# one-time: daemon + images
dockerd &
bash constellation-gate/tests/e2e/docker/scripts/build_images.sh all

# every run: clean slate -> boot -> scenarios -> evidence -> verdict
bash constellation-gate/tests/e2e/docker/scripts/gen_env.sh /root/l9e2e/run.env
bash constellation-gate/tests/e2e/docker/scripts/run_e2e.sh
```

Evidence lands in
`constellation-gate/.l9/runtime/docker-e2e/<UTC-timestamp>/` with
`assertions.json` carrying the verdict. Exit status is non-zero on any
mandatory-scenario failure; a scenario that did not run counts as a failure,
never as a pass.
