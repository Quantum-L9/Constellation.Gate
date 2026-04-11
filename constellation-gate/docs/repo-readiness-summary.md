



Gate repo readiness summary
Complete now
Canonical TransportPacket ingress boundary

Strict routing-policy enforcement

Gate-only dispatch authority

Node registry, resolver, dispatcher

Workflow engine and workflow execution path

Execute service with:

idempotency

replay guard

retry policy

timeout policy

metrics

tracing/logging hooks

Admin registration flow

Registry query flow

Health and metrics routes

Architecture tests for:

no direct node-to-node

Gate dispatch authority

lineage reentry

Integration coverage for:

node → Gate → worker

workflow execution path

admin register → registry snapshot

Packaging, CI, pre-commit, repo docs, agent instructions

Intentionally simple / in-memory now
These are acceptable for dev/test but should be externalized or hardened for production:

NodeRegistry is in-memory

IdempotencyStore is in-memory

ReplayGuard is in-memory

ExecutionState is minimal and not persisted

Workflow definitions are process-local

Health monitor uses simple polling

No durable dead-letter queue

No circuit breaker / load shedding / rate limiter yet

No distributed trace export backend

No persistent audit/event stream

Production interpretation
The repo is code-complete and architecture-complete, but not yet infra-complete for serious production load.

Release-grade checklist
Green now
Build passes

Unit tests pass

Integration tests pass

API surface coherent

Routing law enforced

Lineage semantics proven

Gate authority preserved

Docs and config present

Must confirm before production deploy
External durable registry strategy

External durable idempotency/replay storage

Configured metrics scraping and alerting

Secure admin auth model

Backpressure/rate limit policy

Failure quarantine / DLQ policy

Multi-instance behavior under duplicate traffic

Operational runbooks

Exact next 3 operational upgrades
1. Externalize resilience state
Replace in-memory:

NodeRegistry

IdempotencyStore

ReplayGuard

with durable/shared backends so multiple Gate instances behave consistently.

2. Add admission control
Implement:

rate limiter

backpressure guard

load shedding

circuit breaker

so Gate degrades safely under overload instead of failing noisily.

3. Add operator-grade observability
Wire:

structured logs to centralized sink

Prometheus alerts/dashboards

distributed trace export

durable execution/audit events

so failures, hot nodes, replay storms, and workflow bottlenecks are visible immediately.

Productionization plan: externalize Gate shared state
Objective
Externalize Gate shared state for:

registry

idempotency

replay protection

dead-letter queue

without changing:

Gate-only routing authority

TransportPacket semantics

current execution ordering

architecture invariants

1. Target state model
Control-plane rule
Gate remains the only authority that:

validates ingress

resolves action → node

dispatches work

records routing outcomes

External stores are state backends, not decision-makers.

Shared-state components
RegistryStore

IdempotencyStore

ReplayStore

DeadLetterStore

Each gets:

a strict interface

one in-memory implementation

one external implementation later

identical behavioral contract

2. Core interface model
RegistryStore
Responsibilities:

register/update node entries

list nodes

resolve by node name

enumerate candidates by action

update health and active counts atomically enough for routing correctness

Required operations:

class RegistryStore(Protocol):
    def upsert_node(self, node_name: str, registration: NodeRegistration) -> None: ...
    def get_node(self, node_name: str) -> NodeRegistration | None: ...
    def list_nodes(self) -> dict[str, NodeRegistration]: ...
    def list_nodes_for_action(self, action: str) -> list[NodeRegistration]: ...
    def set_health(self, node_name: str, healthy: bool) -> None: ...
    def increment_active(self, node_name: str) -> None: ...
    def decrement_active(self, node_name: str) -> None: ...
Deterministic rule:

resolver still chooses target inside Gate code

store only returns state

tie-breaking remains local and deterministic

IdempotencyStore
Responsibilities:

check for completed semantic request by idempotency key

store canonical response packet JSON

support safe multi-instance reuse

Required operations:

class IdempotencyStore(Protocol):
    def get(self, key: str) -> dict[str, Any] | None: ...
    def put_if_absent(self, key: str, value: dict[str, Any], ttl_seconds: int | None = None) -> bool: ...
    def set(self, key: str, value: dict[str, Any], ttl_seconds: int | None = None) -> None: ...
Deterministic rule:

cached value must always be a canonical TransportPacket.model_dump_json_dict()

key space is exactly packet.header.idempotency_key

no packet mutation during retrieval

ReplayStore
Responsibilities:

detect duplicate packet IDs across Gate replicas

enforce replay window

Required operations:

class ReplayStore(Protocol):
    def seen(self, packet_id: str) -> bool: ...
    def record(self, packet_id: str, ttl_seconds: int) -> None: ...
    def check_and_record(self, packet_id: str, ttl_seconds: int) -> None: ...
Deterministic rule:

replay identity is packet.header.packet_id

replay protection is about duplicate transport submission, not semantic dedupe

idempotency and replay remain separate concerns

DeadLetterStore
Responsibilities:

persist terminal failed packets

allow later operator inspection/replay tooling

Required operations:

class DeadLetterStore(Protocol):
    def put(self, entry: DeadLetterEntry) -> None: ...
    def latest(self) -> DeadLetterEntry | None: ...
    def list(self, limit: int = 100) -> list[DeadLetterEntry]: ...
Deterministic rule:

entry contains canonical packet JSON + failure metadata

write occurs only after terminal failure, not transient retryable failures

3. Implementation split
New module layout
src/constellation_gate/state/
  interfaces.py
  memory/
    registry_store.py
    idempotency_store.py
    replay_store.py
    dead_letter_store.py
  external/
    registry_store.py
    idempotency_store.py
    replay_store.py
    dead_letter_store.py
Design rule
routing/node_registry.py becomes Gate-facing façade over RegistryStore

ExecuteService depends on store interfaces, not concrete in-memory helpers

current in-memory behavior becomes default implementation for local/dev

4. Migration order
Phase 1 — Interface extraction
Goal: zero behavior change

Steps:

introduce store protocols

wrap current in-memory implementations behind those interfaces

update NodeRegistry, ExecuteService, and resilience code to depend on interfaces

keep all tests green with current in-memory behavior

Success condition:

no externally visible behavior changes

same tests pass unchanged or with minimal constructor wiring updates

Phase 2 — Registry externalization
Goal: shared routing view across Gate replicas

Steps:

introduce external RegistryStore

change NodeRegistry to use store-backed reads/writes

preserve resolver tie-break in Gate code

add registry freshness/version tests

Success condition:

two Gate instances reading same backing store resolve from same node pool

health changes become visible cross-instance

Failure guard:

if external store unavailable, Gate must fail closed for routing mutations, not invent local shadow state silently

Phase 3 — Idempotency + replay externalization
Goal: duplicate-safe multi-instance execution

Steps:

introduce external IdempotencyStore

introduce external ReplayStore

update ExecuteService wiring

add concurrent duplicate tests across simulated Gate instances

Success condition:

same idempotency key returns same stored response across instances

duplicate packet ID is rejected across instances inside replay window

Failure guard:

if replay/idempotency backend is required for prod and unavailable, Gate should reject execution rather than downgrade silently

Phase 4 — Dead-letter externalization
Goal: durable failure quarantine

Steps:

introduce external DeadLetterStore

keep same DeadLetterEntry shape

write terminal failures durably

add admin/operator listing flow later

Success condition:

terminal failures survive process restart

DLQ entries remain queryable

5. Failure modes and handling
Registry backend unavailable
Risk:

inconsistent routing

stale health

split-brain dispatch

Handling:

reject admin registration mutations

reject worker dispatch if registry cannot provide authoritative state

surface explicit operational error

do not fallback silently to partial local routing state in prod mode

Idempotency backend unavailable
Risk:

duplicate semantic execution across replicas

Handling:

in prod mode: fail closed for actions requiring idempotency

in dev mode: allow configured in-memory fallback only if explicitly enabled

Replay backend unavailable
Risk:

duplicate transport acceptance

Handling:

in prod mode: reject execution when replay protection is required

in dev mode: optional local fallback

Dead-letter backend unavailable
Risk:

loss of failure quarantine record

Handling:

execution failure still propagates

emit high-severity log/metric

optionally fallback to local memory buffer, but mark degraded mode explicitly

6. Consistency model
Registry
Consistency target:

read-your-writes for registration/admin flows

near-real-time visibility for health/active updates

resolver tie-break remains deterministic from returned snapshot

Do not push routing choice into store.

Idempotency
Consistency target:

atomic first-writer-wins for a given key

later readers get same response blob

Replay
Consistency target:

atomic check-and-record

Dead-letter
Consistency target:

at-least-once write acceptable

duplicate DLQ entries tolerable if packet ID + error timestamp distinguish them

7. ExecuteService integration changes
Current
ExecuteService owns in-memory:

idempotency store

replay guard

dead-letter queue

Target
ExecuteService receives:

ExecuteService(
    ...,
    idempotency_store: IdempotencyStore,
    replay_store: ReplayStore,
    dead_letter_store: DeadLetterStore,
)
Execution order remains:

validate

admission control

idempotency lookup

replay check-and-record

execute

cache response

on terminal failure → dead-letter write

No routing-law changes.

8. Testing strategy
Unit tests
Add interface contract tests for each store:

memory implementation

external implementation

same inputs → same outputs

Concurrency tests
Critical:

two simulated Gate instances share same idempotency store

two simulated Gate instances share same replay store

same packet/idempotency key submitted concurrently

Expected:

one success path, one cached/rejected path

no double execution

Integration tests
Add:

shared registry across two Gate instances

shared idempotency across two Gate instances

shared replay across two Gate instances

DLQ durability simulation

Failure-path tests
Add:

backend unavailable

partial write failure

stale registry read

duplicate DLQ insertion

9. Deployment strategy
Configuration additions
STATE_BACKEND=memory|external
REGISTRY_BACKEND_URL=
IDEMPOTENCY_BACKEND_URL=
REPLAY_BACKEND_URL=
DLQ_BACKEND_URL=
STATE_STRICT_MODE=true
Modes
memory: local/dev

external: prod

STATE_STRICT_MODE=true: fail closed if required shared state backend unavailable

10. Definition of done
This migration is done when:

all current behavior remains unchanged in memory mode

shared-state mode passes multi-instance tests

duplicate execution is prevented across Gate replicas

routing still resolves only inside Gate code

dead-letter entries persist beyond process lifetime

no architecture tests regress

no direct node-to-node semantics appear

YNP: Generate the Phase 1 implementation pass: a 5-file, execution-ready refactor plan for extracting shared-state interfaces and wrapping the current in-memory registry/idempotency/replay/DLQ implementations behind them without changing current Gate behavior.

Use this as your next prompt?


Why/when would I want to do that?

You want to do it when you move from a single Gate process to real production operation.

Why
Because right now those parts are process-local memory:

registry

idempotency

replay protection

dead-letter queue

That is fine for:

local dev

tests

one-instance deployment

early staging

It becomes a problem when you have 2+ Gate instances, restarts, failover, or rolling deploys.

Concrete reasons
1. Multi-instance correctness
If Gate A and Gate B do not share:

idempotency state

replay state

then the same request can be accepted twice.

That means:

duplicate dispatch

duplicate side effects

broken “safe retry” semantics

2. Restart durability
If Gate restarts and memory is wiped:

replay history is gone

idempotency cache is gone

dead letters are gone

registry state may need rebuilding

So a restart can look like:

“this duplicate packet is new again”

“that failure never happened”

“that node registration disappeared”

3. Horizontal scale
You cannot safely scale Gate replicas if each replica has its own private truth for:

which packets were already seen

which idempotency keys are completed

which nodes are registered/healthy

4. Operational visibility
A dead-letter queue only in memory is weak operationally.
If the process dies, your failure evidence dies with it.

5. Controlled failover
In production, when one Gate instance dies, another should continue with the same control-plane memory for critical execution safety.


===
Inputs:

validated TransportPacket

Outputs:

canonical response TransportPacket

Interaction rules:

Dispatcher must use shared async client only

Dispatcher must acquire per-node permit before POST

ExecuteService must perform admission before dispatch/workflow

all capacity counters must be released in finally

Deterministic execution flow

Atomic request path

receive request

validate TransportPacket

apply rate limit / load shedding / backpressure

increment global in-flight

idempotency lookup

replay check

resolve destination node

ensure node limiter exists from registry config

acquire node semaphore

dispatch through pooled async client

apply retry/timeout rules

release node semaphore

cache idempotent result if needed

emit metrics/logs/traces

decrement global in-flight

Workflow path

receive workflow packet

same admission sequence

workflow engine emits step packets

each step dispatch goes through same per-node acquire/release path

workflow returns final response packet

metrics emitted per step and total workflow

Validation rules, guardrails, failure handling

Guardrails

no unbounded internal queue

no per-request AsyncClient

no dispatch without node permit

no permit leak on cancel/error

no retry on non-retryable admission failures

no node dispatch if node unhealthy

Failure handling

rate limit -> immediate reject

load shed -> immediate reject

backpressure -> immediate reject

node saturated -> deterministic reject or bounded wait policy

timeout -> failure metric + DLQ if terminal

transport error -> retry if allowed

cancellation -> release permit + decrement gauges in finally

Scalability, reuse, composability

This keeps one Gate simple and strong:

one shared connection pool reduces socket churn

per-node semaphores prevent hot-node overload

global admission protects Gate itself

workflow and atomic paths reuse same dispatch pipeline

all later multi-Gate work can reuse the same interfaces

File/module mapping

Primary implementation targets

src/constellation_gate/routing/dispatch.py

src/constellation_gate/services/execute_service.py

src/constellation_gate/runtime/lifecycle.py

src/constellation_gate/runtime/app_state.py

New modules to add

src/constellation_gate/runtime/http_client.py

src/constellation_gate/runtime/node_limits.py

src/constellation_gate/resilience/admission_controller.py

Tests to add

tests/runtime/test_http_client.py

tests/runtime/test_node_limits.py

tests/services/test_execute_service_admission_order.py

tests/routing/test_dispatch_node_concurrency.py

tests/integration/test_single_gate_async_overload.py

Implementation milestones + DoD

Milestone 1: shared async client
DoD:

one startup-managed AsyncClient

dispatcher uses injected shared client

no per-request client creation remains

Milestone 2: per-node concurrency protection
DoD:

semaphore per node from max_concurrent

dispatch blocks/rejects deterministically at limit

permits always released on success/failure/timeout

Milestone 3: global admission hardening
DoD:

rate limit + load shedding + backpressure checked before dispatch

rejection reasons explicit and metrically visible

Milestone 4: timeout and retry coherence
DoD:

end-to-end timeout wraps execution

dispatch timeout derived consistently

retry does not bypass admission semantics

terminal failures hit DLQ

Milestone 5: async stress validation
DoD:

concurrent tests prove one Gate can safely fan out to many nodes

no leaked permits

no unbounded queue growth

hot node saturation does not collapse whole Gate
