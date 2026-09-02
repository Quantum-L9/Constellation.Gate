# EIE ↔ Gate ↔ CEG seam — forensic audit (2026-09-02)

Scope: Quantum-L9/Enrichment.Inference.Engine (EIE), Quantum-L9/Cognitive.Engine.Graphs (CEG),
Quantum-L9/Constellation.Gate (Gate), Quantum-L9/Gate_SDK. Branch on every repo:
`claude/gateway-seam-forensic-audit-m7cqt6`. Companion machine-readable files sit next to this document.

## 1. Bound heads

| Repo | Start head (== origin/main at audit start) | Final head (branch) |
|---|---|---|
| Enrichment.Inference.Engine | 64c5676d645ea6e1b30189456df68652ac5be35a | 02e3699d7f4bc48e6a06de8a57f57f1ec2852b2a |
| Cognitive.Engine.Graphs | 514ae6ce6bf32a87c6624d21fbaf3a4913a32d65 | 38fc3defdc8b4334e4248a55fea2839a1a74d8fc |
| Gate_SDK | a0827f2b94e77a981c6d6be88653e4975cf631ef | 69c6c67060b08440734a61473c03663423709964 |
| Constellation.Gate | d210539fed7ddd4d82d13e9adcc3eeafcb6e498b | the commit that adds this file (see `git log -1 -- docs/seam-audit/2026-09-02`) |

Open PRs at start: none on EIE, Gate, Gate_SDK; CEG had dependabot PRs #249–#258 only (unrelated). Open issues: none.
Graphiti memory held nothing material about this seam.

## 2. Method

1. Census of every communication surface: Gate_SDK imports, HTTP clients, FastAPI routes, message-bus producers/consumers, peer URL settings, deployment env, in all four repos.
2. Transitive file closure from those surfaces; deep read of every file in the closure (listed per repo in the session record; the material ones are named in the ledger).
3. Reconstruction of both call graphs (EIE→CEG and CEG→EIE) as they actually existed at the start heads.
4. Side-door forensics with a disposition per candidate (`SIDE_DOOR_CENSUS.yaml`).
5. Contract, route, auth, deadline/retry/idempotency and version alignment (`*_MATRIX.yaml`, `BIDIRECTIONAL_CONTRACT_LOCK.yaml`, `VERSION_COMPATIBILITY_RECEIPT.yaml`).
6. Dependency-ordered repairs: Gate_SDK → Gate → EIE → CEG → side-door sealing → guards.
7. A cross-repo fixture that launches the real Gate, EIE and CEG processes (plus a real Neo4j) and drives both directions over real sockets; failure injection; final re-audit.

## 3. Architecture before

- **EIE→CEG** existed only as a broken sketch: `PacketRouter` sent an unowned action (`graph-sync`) with a payload CEG could not parse, `GraphSyncClient` used `outcome` where CEG serves `outcomes`, three unsigned outbound client configurations, and the SDK runtime was built without signing so preflight would fail closed in staging/prod. Beside it sat five working bypasses: peer URL settings with a shared secret, a raw peer HTTP client, a `POST /v1/outcomes` peer ingress, a Redis-stream result bus, a duplicate sync module, and a Neo4j driver dependency.
- **CEG→EIE** did not exist. The Gate client singleton was never called; the ROI trigger built a payload and returned it unsent; the health handler was not registered as an action.
- **CEG ingress** defaulted to the legacy dict chassis (api-key auth, no Gate provenance), which Gate cannot dispatch to and any peer can call directly. `engine/spec.yaml` advertised 23 `graph-*` actions that were never implemented, so Gate's readiness for CEG was a fiction.
- **Gate** had no owner for `enrich`/`enrich-and-sync`, could not map CEG's runtime node name `graph` to an owner, judged readiness on `converge` alone, cached failure packets under idempotency keys, and shipped a stale static registry.
- **Versions**: EIE and Gate pinned a deleted PR head of Gate_SDK; CEG pinned a much older commit.

## 4. Confirmed side doors and root causes

Eight confirmed (census IDs EIE-SIDE-DOOR-01..06, CEG-SIDE-DOOR-01, CEG-SIDE-DOOR-02). Root causes:

1. **Transport was reinvented per repo** instead of taken from the SDK: hand-built runtime config, three client-config sites, a raw HTTP client, a dict chassis.
2. **No executable route contract**: nothing tied "what EIE sends" to "what CEG serves" to "what Gate owns"; names drifted (`graph-sync`/`sync`, `outcome`/`outcomes`, `graph-*`).
3. **Convenience paths were left in place** (peer URLs, /v1/outcomes, Redis bus) because the sanctioned path did not work.
4. **Version drift** made the SDK surface itself inconsistent across the rail.

## 5. Architecture after

All collaborative traffic is `node → Gate_SDK GateClient → Gate /v1/execute → gate_authority dispatch → peer SDK runtime /v1/execute`, TransportPacket only, signed both ways:

- EIE: one signed client factory; `sync`/`match`/`outcomes` with CEG's payload contracts; bounded key-gated retry; SDK-derived runtime config; every bypass removed and guarded.
- CEG: SDK chassis by default (legacy refused outside dev/test); spec advertises `match, sync, outcomes, resolve`; `engine/gate_egress.request_enrichment` is the only egress and the ROI trigger really dispatches through it.
- Gate: ownership lock for all seven seam actions; readiness requires the whole seam; failures are not cached; registry file and replay-safety aligned.
- Gate_SDK: env-built client config now carries `L9_VERIFYING_KEYS_JSON` (without it every signature-requiring node rejected Gate's signed responses — found only because the E2E was real).

## 6. Evidence

`BIDIRECTIONAL_E2E_RECEIPT.yaml` (18/18 live checks), `FAILURE_INJECTION_RECEIPT.yaml` (10/10 executed, 3 NOT_EXECUTED with reasons), `SIDE_DOOR_SEAL_RECEIPT.yaml` (0 reachable), raw logs and registry snapshot under `evidence/`.

## 7. Findings ledger

`EIE_CEG_GATE_REPAIR_LEDGER.yaml`: P0 0 · P1 14 · P2 11 · P3 8 (33 total; 27 repaired, 4 documented, 2 UNKNOWN).

## 8. What remains UNKNOWN or outside this pass

- Whether the production Neo4j has a database named after the CEG domain id (DEPLOY-03).
- Owner of `score-invalidate` (score node outside scope; EIE now sends once and fails closed).
- Whether any deployment loads Gate's static `node_registry.yaml`.
- A non-failed enrichment domain result (needs LLM provider credentials; transport proven, domain outcome observed as failed).
- The live E2E is not a CI gate yet; Gate_SDK 69c6c67 is on a feature branch and must merge before consumer merges.
