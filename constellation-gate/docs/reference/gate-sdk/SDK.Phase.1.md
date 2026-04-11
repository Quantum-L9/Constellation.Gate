

Constellation.Gate.Node — Full Repository Ingestion.md
File
Let’s dive into https://github.com/cryptoxdog/Constellation.Gate.Node 

Correct. That's the full picture.

## The Canonical Architecture

Client
  ↓  TransportPacket
GATE  (validate → resolve → dispatch → return)
  ↓  TransportPacket
Node A  (enrich / orchestrate / score / memory / ceg)
  ↓  TransportPacket  [needs to call Node B]
GATE  ← back through Gate, not direct
  ↓  TransportPacket
Node B


**Every inter-node call routes back through Gate.** No node has a direct reference to another node's URL. Nodes only know Gate's address.

## Why This Matters

1. **Gate stays the single authority** — all traffic is visible, validated, signed, and traceable through one ingress point. Direct node-to-node calls create invisible channels that bypass validation, signing, and hop tracing entirely.

2. **TransportPacket lineage is correct** — the lineage.hop_trace accumulates every Gate pass. If Node A calls Node B directly, that hop is invisible. Routed through Gate, the full chain is preserved.

3. **Nodes are location-agnostic** — a node doesn't need to know where CEG lives. It sends action: graph.sync to Gate and Gate resolves the destination. Nodes can be redeployed, scaled, or replaced without any consumer updating URLs.

4. **The Orchestrator Node composes freely** — it receives a workflow packet, executes step 1 by sending a packet *to Gate*, waits for the response, sends step 2 *to Gate*, and so on. Gate sees individual atomic dispatches. The orchestration state lives entirely inside the Orchestrator Node.

## What Gate's TransportPacket Upgrade Enables

The source_node in the packet tells Gate who sent it. So when the Orchestrator Node sends action: enrich back through Gate, Gate knows:

- Origin: orchestrator
- Destination: enrich
- Hop trace: client → gate → orchestrator → gate → enrich

The full chain is reconstructed from the packet alone. No out-of-band coordination needed.

## The Clean Constraint

Every node gets exactly one env var for external communication: GATE_URL. That's the entire integration surface. If a node has any other node's URL hardcoded or configured — that's a bug.



Thought for 7s
Yes — that constraint should be treated as architectural law, not an implementation preference.

Given the repo as ingested, your model is cleaner than the currently described execution path in one important way: the existing implementation/report still frames dispatch as GATE resolving a target node and posting directly to that node for the current request path, but it does not yet clearly enforce “all secondary node-to-node work must re-enter GATE” as a hard invariant.

The repo already has most of the primitives needed for your canonical design:

a canonical packet model with address.source_node, address.destination_node, hop_trace, and lineage

GATE as the public routing hub with action resolution via NodeRegistry.resolve() and dispatch via Dispatcher.dispatch()

delegation/history structures that can preserve proof and traversal state across hops

So the architecture you described is not a rewrite. It is a tightening of routing semantics around mechanisms the codebase already has.

Where I would be strict:

A node must never resolve another node.
Today the registry/dispatcher pattern implies resolution happens inside GATE, which is good. But the invariant needs to be explicit in chassis and node templates: child nodes may emit only TransportPacket requests addressed to gate, never to ceg, score, enrich, etc. Otherwise the system drifts into partial mesh.

destination_node from a node-originated packet should usually be gate, not the final worker.
The final worker should be derived by GATE from action, policy, health, and load. That preserves your location-agnostic rule and keeps action→node mapping centralized in NodeRegistry.

Hop trace must record the re-entry hop explicitly.
The meaningful chain is not just logical parentage; it is transport lineage:
client → gate → orchestrator → gate → enrich.
Without the second gate hop, observability and replay semantics become misleading. The packet model already supports hop tracking; the rule needs to be enforced at every dispatch boundary.

GATE_URL should be the only network locator in node runtime config.
That fits the repo’s existing child registration pattern, where nodes already bootstrap against GATE using GATE_URL from env.
I would extend that rule to outbound execution too: registration and invocation both use the same authority.

The biggest architectural consequence is this:

Orchestration moves from being “service composition by network topology” to “workflow composition by packet recursion.”

That is the right move. It means:

the orchestrator owns workflow state

GATE owns routing authority

worker nodes own only local execution

the packet is the only cross-boundary state carrier

That separation is much stronger than the current workflow model in the report, where WorkflowEngine inside GATE executes named workflows directly as a local engine concern.
For simple static workflows that is fine, but for your stated architecture, a dedicated Orchestrator Node is the better abstraction because it keeps composition externalized while still forcing every atomic action back through GATE.

What I would change in this repo to make your constraint mechanically enforceable:

In chassis/gate_client and node-side execution helpers, expose only a send_to_gate(packet) client, never a general-purpose node URL dispatcher.

Add ingress validation in GATE that rejects node-originated packets whose destination_node != gate unless they are already GATE-issued delegations.

Add a policy test: no node config may include peer node URLs outside GATE bootstrap/registration concerns.

Make source_node mandatory for all non-client-originated packets so GATE can reconstruct full hop lineage deterministically.

Add contract tests asserting:

Node A cannot call Node B directly

Node A can call GATE with action=graph.sync

GATE resolves and dispatches to B

returned packet preserves root_id, increments lineage correctly, and appends both hops

One subtle point: your model also resolves a weakness in the current report around workflow typing and execution ambiguity. The ingestion notes that WorkflowEngine.execute() is loosely typed and can blur dict versus PacketEnvelope handling.
If orchestration becomes packet-native and every step is “emit packet to GATE, receive packet back,” that ambiguity largely disappears. Everything becomes envelope-in, envelope-out.

So my read is:

your architecture is the correct canonical model

the repo is close structurally

the missing piece is not capability, it is enforcement

the system should be hardened so any direct peer-to-peer node call is impossible by construction

The clean mental model is:

Nodes execute. Orchestrators compose. GATE resolves. Packets remember everything.

That is the version worth codifying in tests, chassis APIs, and validation rules.


Where would the boundary be between an ingress node and an orchestrator node in a constellation (distributed system)?

The boundary is:

Ingress decides whether a request may enter the constellation.
Orchestrator decides how admitted work is decomposed and sequenced inside it.

In a clean distributed design, those are different responsibilities, even if a small system temporarily hosts them in the same process.

The practical split
Ingress node owns the admission boundary
It is the control point at the edge of the constellation.

Its job ends once a packet is:

accepted or rejected

normalized into the canonical transport format

authenticated / signed / validated

classified for policy, tenancy, and routing eligibility

assigned trace, lineage, and initial priority

handed to the next internal authority

So ingress is about:

trust boundary

protocol boundary

policy boundary

observability boundary

It answers:
“Should this request be allowed into the system, and under what envelope?”

In your repo terms, this is the GATE-style behavior: validate, resolve, dispatch, preserve lineage/hop trace, and remain the single visible authority for traffic admission and routing.

Orchestrator node owns the workflow boundary
It is an internal control-plane actor, not the public trust boundary.

Its job begins after a request is already admitted and canonicalized.

It decides:

which steps are needed

in what order

with what branching conditions

what intermediate state to keep

when the workflow is complete, failed, or compensating

So orchestrator is about:

decomposition

sequencing

stateful coordination

retries / compensations

result assembly

It answers:
“Given an already valid packet, what internal work graph should be executed?”

The clean handoff
The cleanest boundary is:

Client sends to Ingress

Ingress validates and stamps the packet

Ingress routes to Orchestrator if the action represents a composite workflow

Orchestrator sends each atomic step back through Ingress/GATE

Ingress resolves each atomic action to the appropriate worker node

Orchestrator accumulates state and returns the final result

So ingress never owns business workflow state.
And orchestrator never owns trust admission.

That gives you this separation:

Client
  ↓
Ingress/Gate
  - auth
  - validation
  - canonicalization
  - policy
  - trace/lineage init
  - routing authority
  ↓
Orchestrator
  - workflow state
  - step sequencing
  - retries/branching
  - accumulation
  ↓
Ingress/Gate
  - per-step routing
  ↓
Workers
The litmus test
A good rule is:

If the concern exists because the caller is outside the constellation, it belongs to ingress.

If the concern exists because the work is multi-step inside the constellation, it belongs to orchestrator.

Belongs to ingress
API shape translation

request size limits

signature verification

tenant authentication

rate limiting

packet schema validation

destination authority

initial hop trace creation

replay protection

compliance tagging

Belongs to orchestrator
execute enrich then sync then score

choose branch B if confidence > 0.7

wait for step 1 result before step 2

aggregate partial outputs

retry a failed step with backoff

abort or continue based on workflow semantics

What should never cross the boundary
The orchestrator should not:

authenticate external callers

expose public ingress APIs as its core role

know peer worker URLs

directly call worker nodes by address

become a second routing authority

The ingress should not:

hold long-lived workflow state

implement complex business sequencing logic

become the place where every domain workflow is hardcoded

That last point matters. Your repo currently includes a WorkflowEngine inside GATE, which is workable for simple flows, but architecturally it starts to blur the boundary once workflows become first-class coordination logic rather than lightweight routing macros.

A useful mental model
Think of it this way:

Ingress is the border checkpoint

Orchestrator is the mission commander

Workers are specialists

The border checkpoint does not plan the mission.
The mission commander does not control the border.

The strongest architectural version
For your constellation, I would define the boundary as:

Ingress/GATE is the sole network authority. Orchestrator is a packet-native internal client of GATE.

That means the orchestrator is just another node from a transport perspective, but a special one from a coordination perspective:

it receives admitted workflow packets

it emits step packets back to GATE

GATE resolves each step

the orchestrator maintains all workflow-local state

That is the cleanest split because it preserves:

single ingress authority

full hop lineage

location-agnostic nodes

testable orchestration semantics

The short architectural rule:

Ingress owns legitimacy. Orchestrator owns composition.


Help me execute that. 

Generate a **high-leverage, execution-grade system plan** for the **next optimal step** based on current context and prior outputs.  Objective: Design a comprehensive, scalable, and fully executable plan that maximizes leverage, accelerates progress, and compounds system capability for whatever the most valuable next move is.  Constraints: - derive the step strictly from prior context, outputs, and system direction - do not invent unrelated work or drift scope - prioritize actions that increase:   - leverage   - automation   - composability   - scalability - no vague steps, no filler, no placeholders - every component must directly contribute to meaningful system advancement - plan must be immediately implementable by a coding agent  Execution Logic: 1. Identify the single highest-leverage next step (explicitly define it). 2. Define the core system model required to execute that step. 3. Decompose into required components:    - modules/services    - contracts/interfaces    - data/state structures (if applicable)    - execution flows/pipelines 4. Map each component to concrete responsibilities. 5. Define explicit interfaces:    - inputs/outputs    - data flow    - interaction rules between components 6. Specify deterministic execution flow (step-by-step). 7. Define validation rules, guardrails, and failure handling. 8. Ensure scalability, reuse, and composability across the system.  Output: 1. identified next step (clear and justified) 2. system overview 3. component breakdown (modules + responsibilities) 4. execution flow (ordered, deterministic) 5. data/state model (if applicable) 6. file/module mapping 7. implementation milestones + DoD per milestone  Goal: Produce a precise, build-ready execution plan for the highest-leverage next move, enabling rapid implementation and compounding system advantage. 


Thought for 10s
1. Identified next step
Implement and enforce a Gate-only inter-node invocation contract across the constellation.

Why this is the single highest-leverage move
This is the narrowest change that unlocks the most downstream advantage:

it converts your canonical architecture from convention into enforcement

it prevents topology drift into hidden peer-to-peer channels

it centralizes routing, validation, signing, lineage, and observability in one place

it makes an Orchestrator Node viable without introducing a second routing authority

it creates a reusable transport contract every future node can adopt

This step compounds because once it exists, every new workflow, node, and capability inherits the same execution model:

nodes execute locally, Gate routes globally, orchestrators compose by sending packets back to Gate.

2. System overview
Objective
Refactor the constellation so that every outbound call originating from a node is sent only to Gate, and Gate alone resolves and dispatches the actual destination node.

Architectural outcome
After implementation:

Client
  ↓
Gate ingress
  ↓
Orchestrator / Worker Node
  ↓
Gate-only outbound client
  ↓
Gate resolution + validation + dispatch
  ↓
Target Worker Node
Success condition
It becomes impossible by API design and validation rules for a node to directly call another node URL.

Core model
Introduce a strict transport model with three authorities:

Ingress authority: Gate

validates admission

resolves destination

appends authoritative hop trace

dispatches to internal target

Execution authority: worker/orchestrator nodes

execute local logic

emit follow-up packets only to Gate

never resolve peer location

Packet authority: TransportPacket

carries source identity

carries logical destination intent

carries lineage and hop trace

is the only cross-node coordination artifact

3. Component breakdown
A. Gate-only outbound transport client
Purpose
Provide the only sanctioned way for any node to invoke external constellation work.

Responsibilities
send packet to GATE_URL

require source_node

normalize node-originated requests as destination_node=gate

preserve lineage and delegation metadata

sign outbound packet if node signing is enabled

reject arbitrary peer URLs

Required interface
send_to_gate(packet: PacketEnvelope) -> PacketEnvelope

Key rule
No generic dispatch(url, packet) helper may remain available to node code.

B. Node-originated packet policy
Purpose
Define the transport rules for packets emitted by internal nodes.

Responsibilities
require packet origin classification: client-originated vs node-originated

require address.source_node for node-originated packets

require address.destination_node == gate for node-originated requests

allow Gate itself to produce internal dispatch packets to worker nodes

preserve lineage.root_id across recursive calls

Key rule
A node may express intent by action, not routing by peer address.

C. Gate ingress enforcement layer
Purpose
Make Gate reject topology violations at the boundary.

Responsibilities
detect node-originated packets

reject packets from nodes targeting non-Gate destinations

validate source identity against registry / known node set

append ingress hop on every re-entry

resolve final destination from action and policy

dispatch only after policy validation succeeds

Key rule
Gate becomes the only legal router for internal cross-node work.

D. Internal dispatch contract
Purpose
Separate external ingress semantics from internal Gate-issued dispatch semantics.

Responsibilities
represent Gate-issued dispatch packets distinctly

mark packets as Gate-routed / Gate-authorized

append hop trace before dispatch

preserve source lineage from the original node

Key rule
Only Gate may create packets that target an internal worker node directly.

E. Orchestrator execution pattern
Purpose
Create the reusable model for composite workflows.

Responsibilities
receive a workflow packet

maintain workflow-local state

emit each atomic step back to Gate

wait for step response

merge step output into accumulated state

return final response packet

Key rule
The orchestrator is a stateful internal client of Gate, not a router.

F. Validation and policy test suite
Purpose
Make architectural law executable.

Responsibilities
prove direct node-to-node calls are rejected

prove node-to-Gate calls succeed

prove Gate resolves by action

prove hop trace includes every Gate re-entry

prove lineage is preserved across recursive composition

Key rule
Architecture is incomplete until enforced by tests.

4. Core contracts and interfaces
4.1 Packet role model
Add or formalize these semantics in the packet model.

Packet classes
Ingress request

sender: external client or edge caller

target: gate

Node-originated request

sender: internal node

target: gate

purpose: request additional constellation work

Gate dispatch

sender: gate

target: resolved worker node

purpose: internal forwarding only

Response

sender: current executor

target: reply path / caller context

4.2 Required packet fields
Header
packet_id

packet_type

action

version

priority

created_at

timeout_ms if used

Address
source_node

destination_node

reply_to

Lineage
root_id

parent_id

generation

Hop trace entry
hop_index

node

direction (ingress, dispatch, response)

timestamp

packet_id

Optional policy extension
Add one explicit routing hint block:

routing: {
    "origin_kind": "client" | "node" | "gate",
    "resolved_by_gate": bool,
    "requested_action": str,
}
This is not strictly required, but it makes validation and debugging much simpler.

4.3 Explicit interfaces
Interface: Node → Gate client
class GateExecutionClient(Protocol):
    async def send_to_gate(self, packet: PacketEnvelope) -> PacketEnvelope: ...
Input
canonical PacketEnvelope

Output
canonical PacketEnvelope response

Rules
destination must be rewritten or validated as gate

no arbitrary base URL except GATE_URL

source node required

must not accept target node URL as parameter

Interface: Gate ingress validator
class NodeOriginPolicyValidator(Protocol):
    def validate_node_origin(self, packet: PacketEnvelope) -> None: ...
Input
inbound packet

Output
none or validation exception

Rules
if source_node != client and source is a registered node:

destination must equal local Gate node

reject packets that attempt direct peer addressing

reject unknown node identities for node-originated traffic

Interface: Gate action resolver
class RouteResolver(Protocol):
    def resolve_action(self, action: str) -> NodeRegistration: ...
Input
logical action

Output
resolved node registration

Rules
only Gate may invoke this for cross-node transport

workers/orchestrators do not import or use it

Interface: Gate dispatcher
class InternalDispatcher(Protocol):
    async def dispatch_resolved(
        self,
        packet: PacketEnvelope,
        destination: NodeRegistration
    ) -> PacketEnvelope: ...
Input
Gate-authorized packet

resolved destination

Output
response packet

Rules
appends Gate dispatch hop

marks dispatch packet as Gate-originated internal forward

updates node concurrency counters and health state

5. Data/state model
5.1 Node transport policy
@dataclass(frozen=True)
class TransportPolicy:
    local_node: str                 # "gate" on Gate, node name elsewhere
    gate_url: str
    require_source_node: bool = True
    enforce_gate_only_egress: bool = True
    allow_direct_internal_dispatch: bool = False  # False for nodes, True only within Gate
5.2 Routing provenance
class RoutingProvenance(BaseModel):
    origin_kind: Literal["client", "node", "gate"]
    requested_action: str
    resolved_by_gate: bool = False
    original_source_node: str | None = None
5.3 Hop trace entry
class HopEntry(BaseModel):
    hop_index: int
    node: str
    direction: Literal["ingress", "dispatch", "response"]
    packet_id: str
    parent_packet_id: str | None = None
    timestamp: datetime
5.4 Validation error taxonomy
class RoutingPolicyError(L9BoundaryError):
    error_code: Literal[
        "node_direct_dispatch_forbidden",
        "unknown_node_origin",
        "missing_source_node",
        "invalid_gate_routing_state",
    ]
6. Deterministic execution flow
Flow A: external request enters constellation
client posts request to Gate

Gate validates packet shape, signature, tenancy, policy

Gate appends ingress hop

Gate determines whether action is:

atomic → resolve + dispatch

composite → send to orchestrator node

Gate dispatches internal packet to resolved node

node executes and returns response packet

Gate returns response to caller

Flow B: orchestrator invokes an atomic step
orchestrator receives workflow packet from Gate

orchestrator updates local workflow state

orchestrator builds a new packet for step action

orchestrator sets:

source_node = orchestrator

destination_node = gate

lineage.root_id = inherited root

lineage.parent_id = current packet_id

orchestrator sends packet using send_to_gate()

Gate validates node-origin policy

Gate appends ingress hop for re-entry

Gate resolves destination from action

Gate dispatches to worker node

worker returns response

Gate returns response packet to orchestrator

orchestrator merges result and continues or completes

Flow C: forbidden direct node-to-node attempt
node constructs packet with:

source_node = node-a

destination_node = node-b

packet arrives at Gate or is attempted through banned API

failure mode:

node-side client rejects before send, or

Gate ingress validator rejects on receipt

return deterministic error:

node_direct_dispatch_forbidden

packet is not forwarded

Flow D: Gate internal dispatch
Gate resolves action -> target node

Gate derives a dispatch packet

Gate sets:

source_node = gate

destination_node = target node

provenance origin_kind = gate

provenance resolved_by_gate = True

Gate appends dispatch hop

dispatcher posts to target internal URL

response is returned and propagated upward

7. Validation rules, guardrails, and failure handling
7.1 Validation rules
Rule 1
All node-originated packets must include source_node.

Rule 2
All node-originated requests must target gate.

Rule 3
Only Gate may emit packets targeting a worker node directly.

Rule 4
Gate resolves worker destination from action, never from node-supplied peer URL.

Rule 5
Every Gate re-entry appends a hop trace entry.

Rule 6
Every internal follow-up preserves lineage.root_id.

Rule 7
A node runtime may expose only GATE_URL for constellation egress.

7.2 Guardrails
Code-level guardrails
remove or deprecate generic node URL dispatch helpers from node-facing APIs

make node-side outbound helper constructor accept only GATE_URL

isolate route resolution classes under Gate package only

introduce type wrappers for NodeOriginatedPacket vs GateDispatchPacket if helpful

Config guardrails
no node-specific peer URL env vars in node templates

static lint / config check: node services may define GATE_URL, not ENRICH_URL, CEG_URL, etc.

Test guardrails
contract tests must fail if a node can invoke peer URL directly

regression tests for hop trace and lineage continuity

7.3 Failure handling
Failure: unknown node origin
Return boundary error, no dispatch.

Failure: node attempts direct peer routing
Return 403 or policy violation equivalent in packet form, no dispatch.

Failure: Gate cannot resolve action
Return unroutable-action error to caller node, preserving lineage.

Failure: resolved node unhealthy
Return unhealthy-target error; orchestrator may decide retry/backoff/alternate flow.

Failure: dispatch timeout
Gate marks node unhealthy per current mechanism, returns structured failure.

Failure: malformed follow-up packet
Reject at ingress validator before routing.

8. Scalability, reuse, and composability
Why this scales
workers remain stateless and location-agnostic

routing remains centralized and hot-swappable

orchestration can expand into many specialized orchestrator nodes without topology sprawl

action resolution can evolve independently of node implementations

observability remains complete because all work crosses Gate

Why this is composable
every node becomes both executor and Gate client using the same packet contract

every workflow becomes composition of atomic actions through one invocation path

retries, policy, signing, replay, and auditing can be added once at Gate instead of per node pair

Why this is reusable
The same transport discipline works for:

orchestrator nodes

memory nodes

graph/sync nodes

replay engines

async job launchers

future multi-region Gate federations

9. File/module mapping
This assumes the current repo layout from the ingested report.

Existing files to modify
chassis/gate_client.py
Add or refactor into the sanctioned Gate-only execution client.

Add

send_to_gate(packet)

policy enforcement for destination = Gate

signing + response decoding

chassis/router.py
Remove any node-facing capability that encourages direct peer dispatch.

Change

delegation helpers should emit packet-to-Gate behavior for nodes

local handler execution remains unchanged

cross-node execution path should call Gate client, not peer URL

chassis/packet_envelope.py
Strengthen packet model semantics.

Add

optional routing provenance block

helper methods:

as_node_originated_request()

as_gate_dispatch()

append_hop(...)

derive_child(...)

gate/engine/handlers.py
Enforce node-origin policy and Gate-only routing.

Add

branch for node-originated ingress

validation call for node-origin policy

explicit path:

validate

append ingress hop

resolve action

dispatch

engine/boundary/ingress_validator.py
Add policy validation for node-originated packets.

Add

validate_node_origin(packet)

new error codes for routing policy violations

gate/engine/dispatch.py
Ensure only Gate issues worker-targeted dispatch packets.

Change

derive Gate dispatch packet before HTTP post

append dispatch hop

preserve root lineage and original source provenance

gate/engine/node_registry.py
May remain mostly unchanged.

Optional additions

helper is_registered_node(source_node)

policy-aware source validation support

New files recommended
chassis/gate_execution_client.py
Single-responsibility outbound Gate client.

engine/boundary/routing_policy.py
Pure policy validation and packet role classification.

tests/test_gate_only_egress.py
Contract tests for node-origin restrictions.

tests/test_lineage_reentry.py
Hop trace and root/parent lineage verification.

tests/test_orchestrator_pattern.py
End-to-end orchestrator → Gate → worker → Gate response loop.

10. Implementation milestones + Definition of Done
Milestone 1: Formalize the transport policy
Deliverables
packet role semantics documented in code

routing provenance model added

helper constructors for node-origin and Gate-dispatch packets

DoD
packet model can represent:

client ingress

node-origin request to Gate

Gate dispatch to worker

unit tests prove helpers set fields deterministically

Milestone 2: Build the Gate-only outbound client
Deliverables
send_to_gate() client implemented

node code path cannot accept arbitrary peer URL

destination normalization to Gate enforced

DoD
a node can send a packet to Gate using only GATE_URL

attempts to pass a peer URL are impossible or rejected

signing + deserialization work end-to-end

Milestone 3: Enforce node-origin ingress policy in Gate
Deliverables
routing policy validator added

Gate rejects node-originated packets targeting non-Gate destinations

unknown node origins rejected

DoD
policy violations return deterministic structured errors

tests prove direct node-to-node routing is rejected

Milestone 4: Refactor Gate dispatch into explicit Gate-issued internal forwarding
Deliverables
dispatcher derives Gate-authored internal packet

hop trace appends on ingress and dispatch

source provenance preserved

DoD
packet history clearly shows:
client -> gate -> orchestrator -> gate -> worker

root lineage remains stable

parent linkage increments correctly

Milestone 5: Refactor orchestrator execution pattern
Deliverables
orchestrator step execution uses Gate client exclusively

no direct resolution or peer addressing in orchestrator code

workflow state remains local to orchestrator

DoD
composite workflow runs with every step routed via Gate

orchestrator contains no peer node URL awareness

integration test proves sequential multi-step execution

Milestone 6: Harden with contract and regression tests
Deliverables
architecture tests

lineage/hop trace regression tests

config/policy checks for forbidden peer URLs

DoD
test suite fails on any direct peer routing path

test suite proves Gate-only inter-node routing invariant

CI can enforce architecture without manual review

11. Coding-agent execution order
Use this exact order:

Add packet role/provenance model

Implement GateExecutionClient

Refactor node-side delegation helpers to use Gate client only

Add routing policy validator in boundary layer

Enforce validator in gate/engine/handlers.py

Refactor dispatcher to emit Gate-authored internal packets

Implement orchestrator end-to-end step loop through Gate

Add architecture tests and regression suite

Remove or deprecate any peer-direct transport API

That ordering minimizes churn because the transport contract is established first, then enforced at the boundary, then propagated to orchestration.

12. Final build-ready directive
The build-ready next move is:

Turn “all inter-node calls go back through Gate” into a hard transport invariant enforced in chassis, Gate ingress validation, Gate dispatch semantics, and tests.

That is the correct next step because it gives you, in one move:

enforceable ingress/orchestrator separation

complete lineage and hop trace

location-agnostic nodes

reusable orchestration pattern

safer scaling for all future constellation capabilities

If you want, I can turn this into a concrete implementation spec with class signatures, test cases, and patch-by-patch change list against the repo layout.



cryptoxdog-constellation.gate.node-8a5edab282632443.txt
Document
Deep parse full repo. Pin relevant details to chat context. 


Thought for 26s
Parsed. I’m pinning this as the working repo context for the rest of the thread.

Repo reality, not aspiration
This repo is not just “a Gate service.” It is a mixed platform repo with four overlapping layers:

GATE runtime in gate/

shared chassis/runtime core in chassis/

domain/engine runtime in engine/

older / adjacent orchestration pack in chassis-orchestration-pack/ that still exposes direct peer URL patterns

That means the repo already contains both:

the architecture you want

implementation paths that still drift toward older node-to-node or mixed-contract behavior

That tension is the core design fact to keep in mind.

Canonical architectural center
The most stable center of gravity is:

PacketEnvelope / TransportPacket as the canonical wire object

GATE as the single public ingress

NodeRegistry as the action→node authority

Dispatcher as Gate-owned forwarding

workflows as packet-sequenced multi-step execution

lineage + hop trace as first-class protocol state

That matches README.md, ARCHITECTURE.md, the packet schema, and the GATE engine shape.

What is structurally important
1. chassis/ is the protocol core
This is the real substrate:

packet_envelope.py defines immutable packet structure, derive(), with_hop(), content/envelope hashing, lineage generation

security.py owns signing, verification, derived-packet validation, delegation proof generation

router.py owns handler registration, ingress inflation, egress deflation, local execution, and delegation helpers

gate_client.py currently handles registration to Gate, not yet the full Gate-only execution contract you want

chassis_app.py is a reusable generic service shell for non-Gate nodes

This is the place to enforce constellation-wide transport law.

2. gate/ is the kernel
This is the live control plane:

gate/api/main.py exposes /v1/execute, /v1/health, /v1/registry, /v1/admin/register

gate/engine/handlers.py is the main routing entrypoint

gate/engine/node_registry.py resolves actions and tracks health/load

gate/engine/dispatch.py does HTTP forwarding to worker nodes

gate/engine/workflow_engine.py decomposes named workflows

gate/engine/health_monitor.py polls node health

gate/config/node_registry.yaml, priorities.yaml, workflows.yaml are runtime control data

This is where routing authority already lives.

3. engine/ is the shared application/boundary layer
This contains the boundary factories and execution/policy/memory modules that GATE actually imports:

engine/boundary/*

engine/application/*

engine/memory/*

engine/policy/*

engine/execution/*

engine/orchestration/*

Important: GATE imports from engine.boundary.*, not from gate/engine/boundary/*. So the root engine/boundary/ tree is the operational one for handler behavior. The duplicate gate/engine/boundary/ tree is a maintenance hazard.

Current execution model
Today’s practical runtime flow is:

client → Gate /v1/execute → ingress validation / command build / priority classify → workflow check → dispatcher → resolved node /v1/execute → response packet → response factory → optional memory mapping.

Important nuance: the dispatcher currently resolves a target node and posts directly to that node’s internal URL. That is fine for Gate→worker dispatch, but it also shows why your next step must harden node-originated follow-up traffic so only Gate can do internal direct dispatch.

Packet model details that matter for your design
The canonical packet already has the right primitives:

header: packet type, action, priority, timeout, replay fields

address: source_node, destination_node, reply_to

tenant

payload

security: content hash, envelope hash, signature, classification

governance

delegation_chain

hop_trace

lineage: root_id, parent_id, generation

attachments

And PacketEnvelope.derive() automatically creates a new packet id, increments lineage generation, preserves root_id, and sets parent_id to the prior packet. That is exactly the mechanism your orchestrator-through-Gate model should lean on.

Current registry and routing facts
Static bootstrap nodes in config are:

enrich

ceg

score

health-node

classify

NodeRegistry.resolve(action) picks the least-loaded healthy node; resolve_destination(name) routes by explicit node name. Health and concurrency counters already exist. This means the repo already has centralized destination authority; the missing piece is preventing nodes from bypassing it.

Workflow facts
Defined workflows include:

standard_pipeline

enrich_and_match

full_pipeline

conditional_processing

assess_and_fix

The workflow engine supports step action, optional node pinning, timeout, conditional execution, and payload merge modes. It uses AST-constrained condition evaluation. That said, one configured condition is broken: conditional_processing uses a lambda string that the AST validator will reject. Also on_failure exists in YAML but is not actually enforced by the engine.

Important repo inconsistencies already present
These are the highest-signal issues now pinned in context:

Dual boundary implementation
There are two boundary trees:

engine/boundary/

gate/engine/boundary/

GATE uses the root engine.boundary.* imports. Editing the wrong tree is an easy failure mode.

Priority queue is not a real dispatch gate
PriorityPacketQueue.put() is used, but dispatch still proceeds inline. So queue priority currently does not control actual execution order.

Workflow typing is loose
WorkflowEngine.execute() is dict-oriented while Dispatcher.dispatch() is envelope-oriented. This is a real protocol seam mismatch.

Memory mapping is not fully wired
MemoryMapper produces records, but persistence is not actually completed in the Gate flow. Memory integration exists structurally, not end-to-end operationally.

Signature enforcement is environment-sensitive
Security is solid in shape, but enforcement can relax in dev/passthrough modes. Production correctness depends heavily on env configuration.

Old topology leakage exists elsewhere in repo
chassis-orchestration-pack/ and some older service material still reference peer URLs like GRAPH_NODE_URL, SCORE_NODE_URL, etc. That is exactly the anti-pattern your Gate-only egress step is meant to eliminate.

What I’m treating as canonical going forward
For future analysis in this chat, I’m treating these as the operative truths:

Canonical protocol core: chassis/packet_envelope.py, chassis/security.py, chassis/router.py

Canonical Gate routing path: gate/engine/handlers.py, dispatch.py, node_registry.py, workflow_engine.py

Canonical boundary implementation used by Gate: engine/boundary/*

Canonical topology intent: single ingress, hub-and-spoke, packet-native intelligence accumulation

Primary architectural defect: inter-node invocation is not yet hardened into a strict Gate-only transport invariant

Highest-leverage refactor area: chassis outbound transport + Gate ingress policy + Gate dispatch semantics + tests

Pinned conclusion
The repo is already close to your target architecture, but it is still in a transitional state between “packet-centric hub-and-spoke” and “mixed legacy microservice habits.” The most important consequence is:

the protocol model is strong enough; the routing law is not yet enforced strongly enough.

That is now the pinned context I’ll use for the next steps.


I think I wanna start fresh and extract what is useful otherwise I’m u tying spaghetti. Or AM I mistaken and it’s not so bad?

You are not mistaken, but you are also not at “burn it all down” yet.

My read: the repo is salvageable, but only if you stop treating it as one thing. Right now it is several overlapping attempts living in one tree. That creates the spaghetti feeling. The codebase is not uniformly bad; it is architecturally multiplexed.

The real problem
The mess is not mainly low-quality code. It is boundary collapse:

protocol core, service chassis, Gate kernel, and domain engine concerns are interleaved

there are duplicate subsystems

there are legacy paths beside newer packet-native paths

there are at least two architectural eras in the repo at once

That is why it feels heavier than it should.

My blunt assessment
What is worth keeping
These parts are high-value and should almost certainly be extracted, not rewritten:

chassis/packet_envelope.py

chassis/security.py

most of chassis/router.py conceptually, though not necessarily unchanged

Gate registry / dispatch / health-monitor concepts

packet lineage / hop trace model

packet-first contracts in contracts/

test intent around ingress validation, routing, workflows, and registration

Those are the real assets. They encode the constellation model.

What is probably dragging you down
These are the likely spaghetti zones:

duplicate boundary trees:

engine/boundary/

gate/engine/boundary/

mixed runtime shells:

app/

chassis/chassis_app.py

Gate-specific FastAPI app

older orchestration pack with direct peer URL assumptions

workflow logic split between Gate and adjacent orchestration concepts

partially wired memory / policy / execution layers that increase surface area before the transport law is settled

That is architectural drag, not leverage.

So: start fresh or not?
Do not rewrite from scratch
A full rewrite would likely destroy the best part of the repo:
the packet model, security semantics, and operational routing ideas.

You would spend a lot of time rebuilding things you already got right.

Do perform an extraction reset
That is the right move.

Meaning:

create a new clean repo or a new top-level package layout

migrate only the proven primitives

re-import features in dependency order

leave behind duplicate and ambiguous layers

So yes, “start fresh” is correct as a packaging and architecture reset, not as a greenfield conceptual rewrite.

The decision rule
If you can’t answer these in one sentence each, the current tree is too tangled:

What is the canonical packet model?

What is the canonical ingress runtime?

What is the canonical node runtime?

What is the only allowed inter-node transport path?

Which boundary package is real?

Which workflow engine is authoritative?

Right now, several of those answers are ambiguous in the repo. That means your instinct is valid.

Recommended posture
I would not keep developing inside this repo as-is.

I would do a controlled extraction into a fresh structure with only four layers:

protocol-core

packet model

signing / verification

lineage / hop / delegation semantics

gate-kernel

ingress validation

registry

resolution

dispatch

health

admin registration

node-runtime

chassis app for worker/orchestrator nodes

handler registration

Gate-only outbound client

contracts-tests

packet schema

architecture tests

inter-node routing invariant tests

Everything else should have to earn its way back in.

Keep vs discard heuristic
Keep now
Keep only code that is:

canonical

small

test-backed

topology-defining

reusable across all nodes

Quarantine for later
Quarantine code that is:

duplicated

legacy HTTP specific

domain-specific orchestration

partially wired

not necessary to prove Gate-only inter-node routing

Drop outright
Drop anything that:

creates peer URL awareness in nodes

duplicates already-better abstractions

mixes edge admission with workflow composition

has no clear owner in the target architecture

My verdict
It is bad enough that continuing “in place” will slow you down.
It is not bad enough to justify a full rewrite of core concepts.

So the correct move is:

fresh repo / fresh package boundary, selective extraction, hard re-foundation around the packet model and Gate-only routing.

That gives you the psychological reset of starting clean without throwing away the few pieces that already encode the right architecture.

The shortest honest answer is:

You are feeling real architectural spaghetti.
But the right response is extraction, not total reinvention.

I can help you produce a precise salvage matrix next: keep / rewrite / quarantine / delete, file by file.


Generate a filetree for the newly restructured repo so I know which files to move where. 

Yes. Here is the new repo file tree I’d use for the extraction reset, optimized around the architecture we’ve already pinned:

packet-first transport core

Gate as sole ingress/routing authority

worker/orchestrator node runtime

Gate-only inter-node egress

contracts + architecture tests as first-class enforcement


Why this tree works
The key improvement is that each top-level package has exactly one job:

protocol_core/ = the canonical transport language

gate_kernel/ = the only routing authority

node_runtime/ = the reusable worker/orchestrator host shell

orchestrator_runtime/ = composition logic, separate from ingress

contracts/ = protocol truth

tests/architecture/ = enforcement of the non-negotiable rules

That removes the current ambiguity between app/, chassis/, engine/, gate/, and the duplicate boundary trees.

Move map from current repo
Here is the practical mapping.

Move mostly as-is
chassis/packet_envelope.py        -> protocol_core/packet_envelope.py
chassis/tenant_context.py         -> protocol_core/tenant_context.py
chassis/security.py               -> protocol_core/security.py

contracts/packet-envelope.schema.json -> contracts/packet-envelope.schema.json
contracts/PACKET_ENVELOPE_SPEC.md     -> contracts/PACKET_ENVELOPE_SPEC.md
contracts/NODE_REGISTRATION_SPEC.md   -> contracts/NODE_REGISTRATION_SPEC.md
contracts/HEALTHCHECK_READINESS_SPEC.md -> contracts/HEALTHCHECK_READINESS_SPEC.md

gate/engine/node_registry.py      -> gate_kernel/routing/node_registry.py
gate/engine/dispatch.py           -> gate_kernel/routing/dispatch.py
gate/engine/health_monitor.py     -> gate_kernel/routing/health_monitor.py
gate/engine/priority_queue.py     -> gate_kernel/routing/priority_queue.py
gate/engine/workflow_engine.py    -> gate_kernel/orchestration/workflow_engine.py

gate/schemas/registry.py          -> gate_kernel/schemas/registry.py
gate/schemas/workflow.py          -> gate_kernel/schemas/workflow.py

gate/config/node_registry.yaml    -> gate_kernel/config/node_registry.yaml
gate/config/priorities.yaml       -> gate_kernel/config/priorities.yaml
gate/config/workflows.yaml        -> gate_kernel/config/workflows.yaml

engine/policy/*                   -> policy/*
engine/execution/*                -> execution/*
engine/memory/*                   -> memory_substrate/*
database/*                        -> database/*
client/*                          -> clients/*
Move, but refactor during move
chassis/router.py                 -> split across:
                                    - node_runtime/handler_registry.py
                                    - node_runtime/execution_client.py
                                    - protocol_core/codec.py

chassis/gate_client.py            -> split across:
                                    - node_runtime/gate_client.py         (registration)
                                    - node_runtime/execution_client.py    (Gate-only packet send)

chassis/chassis_app.py            -> node_runtime/chassis_app.py
app/config.py                     -> node_runtime/config.py
app/preflight.py                  -> node_runtime/preflight.py
app/observability.py              -> node_runtime/observability.py
app/main.py                       -> examples/worker_node/app.py or thin runtime bootstrap

gate/api/main.py                  -> gate_kernel/api/main.py
gate/api/middleware.py            -> gate_kernel/api/middleware.py

engine/boundary/*                 -> gate_kernel/boundary/*
Do not carry forward as canonical source
These should be treated as reference/quarantine, not migrated directly:

gate/engine/boundary/*            # duplicate boundary tree
chassis-orchestration-pack/*      # older parallel architecture
l9/chassis/*                      # legacy/adjacent duplicate abstractions
app/engines/chassis_contract.py   # transitional adapter, not final core
docs/packetEnvelope/*             # reference only, curate selectively
example_service/*                 # keep only as an example if useful
The one structural rule that matters most
Do not recreate this current anti-pattern in the new repo:

protocol + runtime + gate kernel + engine boundary + orchestration
all mixed under overlapping packages
In the new tree:

only protocol_core may define packet semantics

only gate_kernel may resolve target nodes

only node_runtime may provide outbound node transport

only orchestrator_runtime may hold workflow-local state

architecture tests must enforce that a node cannot directly target another node

Suggested extraction order
Move in this order:

protocol_core/

contracts/

gate_kernel/routing/

gate_kernel/boundary/

node_runtime/

tests/architecture/

orchestrator_runtime/

memory/policy/execution modules

examples and deploy assets

That sequence keeps the transport law stable first, then rebuilds execution around it.

Minimal first-cut repo
If you want the leanest possible starting point, begin with only this:

constellation/
├── protocol_core/
├── gate_kernel/
├── node_runtime/
├── contracts/
├── tests/
│   ├── architecture/
│   ├── protocol_core/
│   ├── gate_kernel/
│   └── node_runtime/
└── README.md
Everything else can be layered back in once the Gate-only routing invariant is proven.

Next I’d recommend producing the old → new migration table file-by-file, so you can physically move the repo without guessing.


Now is the time to upgrade to transport packet 

Agreed. This is the right inflection point.

Do the TransportPacket upgrade first, before more extraction.

Because once the packet is canonical and enforced, the rest of the repo can be moved around safely. Without that, you risk reorganizing code around ambiguous contracts.

What “upgrade to TransportPacket” should mean
Not “add another model.”

It should mean:

one canonical packet type for all ingress, inter-node, and response traffic

legacy dict payloads become a compatibility shim only

every boundary, dispatcher, orchestrator, and worker speaks the same envelope

lineage, hop trace, signing, governance, and routing semantics become mandatory protocol behavior

The repo already has most of this in shape via PacketEnvelope; the upgrade is really about making that model the only authoritative transport contract.

The correct immediate objective
Promote PacketEnvelope into the enforced TransportPacket contract across Gate and nodes, and demote all non-canonical request forms to temporary ingress adapters.

What to do right now
1. Freeze the canonical schema
Declare one source of truth:

contracts/packet-envelope.schema.json

chassis/packet_envelope.py

Then explicitly define TransportPacket = PacketEnvelope at the protocol level, unless you want to rename the class later for clarity.
Do not create parallel models.

2. Make Gate packet-native only internally
At gate/engine/handlers.py level, everything after ingress coercion should operate on PacketEnvelope only.

That means:

validator in → PacketEnvelope

command factory in → PacketEnvelope

workflow engine in/out → PacketEnvelope

dispatcher in/out → PacketEnvelope

response factory in/out → PacketEnvelope

No internal dict[str, Any] flow once past ingress.

3. Collapse legacy ingress to one shim
Support old request bodies only here:

parse legacy dict

convert once to canonical packet

mark as legacy-adapted if needed

continue packet-native from there

No second legacy branch deeper in execution.

4. Add packet role semantics now
You need explicit meaning for these transport cases:

client → gate request

node → gate request

gate → worker dispatch

worker/orchestrator → caller response

That can be done with either:

current fields plus strict rules, or

a small new provenance/routing block

I recommend a small provenance block because it will make Gate-only egress enforcement much easier.

Example:

class RoutingProvenance(BaseModel):
    origin_kind: Literal["client", "node", "gate"]
    requested_action: str
    resolved_by_gate: bool = False
    original_source_node: str | None = None
5. Upgrade hop semantics
Current HopEntry is useful but too execution-status oriented for the architecture you want. It should clearly encode Gate re-entry and Gate dispatch.

Either extend existing HopEntry, or add enough fields to distinguish:

ingress at Gate

dispatch from Gate

execution at worker

response return

Without that, client -> gate -> orchestrator -> gate -> worker will be hard to audit precisely.

6. Make derived packet lineage non-optional
Your orchestrator pattern depends on this being deterministic:

root_id stable across whole workflow

parent_id points to immediate causal packet

generation increments exactly once per derived packet

This already exists in derive(). Keep that behavior and write tests around it.

Minimum upgrade scope
Do not try to solve everything at once.
The immediate upgrade surface is only this:

Protocol core
chassis/packet_envelope.py

chassis/security.py

Gate ingress + dispatch
gate/engine/handlers.py

gate/engine/dispatch.py

engine/boundary/ingress_validator.py

engine/boundary/response_factory.py

engine/boundary/transport_codec.py

Node/runtime compatibility
app/engines/chassis_contract.py

chassis/router.py

Tests
packet lifecycle

ingress validation

dispatch lineage

workflow lineage

legacy-to-packet coercion

The exact upgrade sequence
Phase 1: Canonicalize the packet
lock schema fields

add any missing provenance/routing fields

normalize packet role semantics

ensure schema and model match exactly

Phase 2: Make Gate fully packet-native
remove dict-based flow after ingress

make workflow engine envelope-in/envelope-out

make dispatcher envelope-in/envelope-out

make response factory return envelope only

Phase 3: Add compatibility shim
one adapter for old request shapes

immediate conversion to TransportPacket

no legacy propagation beyond ingress

Phase 4: Enforce transport invariants
source node required for node-originated traffic

destination must be Gate for node-originated requests

only Gate may issue worker-targeted dispatch packets

full hop trace across Gate re-entry

Phase 5: Delete ambiguous transport paths
remove duplicate packet adapters

remove alternative non-canonical execution flows

deprecate direct dict handling in runtime internals

Definition of done
You are “upgraded to TransportPacket” when all of these are true:

every internal execution path uses PacketEnvelope only

legacy request bodies are converted once at ingress and nowhere else

Gate dispatches and workflows operate on canonical packets only

tests prove lineage survives multi-hop orchestration

tests prove Gate re-entry appears in hop trace

node-originated follow-up traffic can be validated as packet-native

Strategic reason this comes first
This is the highest-leverage move because it turns the repo from:

“a set of services with some packet support”

into:

“a packet-governed constellation with services hanging off it.”

That inversion is what you need before enforcing Gate-only inter-node routing and before extracting a clean new repo.

Recommendation
Start with a narrow implementation branch whose sole goal is:

“TransportPacket everywhere inside Gate.”

Not repo cleanup.
Not orchestrator buildout.
Not memory integration.

Just:

canonical packet

envelope-only execution path

legacy ingress shim

lineage/hop correctness

After that, the Gate-only egress refactor becomes much simpler and much safer.

I can turn this into a concrete patch plan next, file by file, with exact edits for the current repo layout.


No shim. Full shift to transport packet. Burn the boats. We’ll make an installable library for nodes that need it 

Good. That is the correct move.

No shim. No dual path. No legacy branch.
Make TransportPacket the only accepted protocol and push compatibility outward into a separate installable node library.

That is much cleaner architecturally.

Decision
Single hard cut:

GATE accepts only canonical TransportPacket

internal dispatch uses only canonical TransportPacket

nodes integrate through an installable SDK/library that builds, signs, validates, and sends TransportPacket

anything not speaking the contract is out

This eliminates the main source of spaghetti: mixed transport eras inside the same runtime.

What this means concretely
GATE becomes protocol-strict
Remove all internal and external support for ad hoc dict payloads and “legacy” request coercion.

From now on:

/v1/execute accepts only canonical packet JSON

validation failure is immediate

no fallback parsing

no silent normalization from non-canonical bodies

Node integration moves to a library
Instead of keeping compatibility logic in GATE, create an installable package for nodes:

constellation-node-sdk
Its job is:

define/export TransportPacket

expose packet builders

expose signing/verification helpers

expose Gate execution client

expose node runtime helpers / chassis hooks

enforce Gate-only outbound transport

So compatibility is not “supported by Gate.”
It is “adopt the SDK or don’t integrate.”

That is the right power move.

New architecture split
You now have two products, not one:

1. constellation-gate
The authoritative ingress and routing kernel.

2. constellation-node-sdk
The installable contract/runtime package for workers and orchestrators.

That separation is exactly what you want if you are burning the boats.

Execution-grade plan for this hard cut
1. Highest-leverage next step
Extract and formalize a standalone TransportPacket SDK, then refactor GATE to depend on it as the sole transport contract.

Why this is first:

it defines the non-negotiable interface once

it lets GATE and nodes share the exact same protocol code

it removes ambiguity before further repo restructuring

it makes every future node adopt the same transport and routing law

2. System overview
Target system shape
client / worker / orchestrator
        │
        ▼
constellation-node-sdk
  - packet model
  - signing / validation
  - packet builder
  - Gate execution client
  - node runtime helpers
        │
        ▼
GATE /v1/execute
  - strict packet ingress
  - validation
  - routing policy enforcement
  - action resolution
  - dispatch
Architectural law
The SDK defines the transport language.

GATE is the only routing authority.

Nodes must use the SDK to participate.

No compatibility logic remains in GATE.

3. Component breakdown
A. transport_packet core module
Responsibility
Canonical packet model and all protocol semantics.

Contents
packet model

header/address/security/governance/lineage/hop types

derive/build helpers

content/envelope hashing

canonical serialization

packet validation primitives

Candidate files
constellation_node_sdk/transport/
├── packet.py
├── models.py
├── lineage.py
├── hop_trace.py
├── hashing.py
├── codec.py
└── errors.py
B. security module
Responsibility
Signing, verification, delegation proof, transport integrity.

Contents
HMAC / Ed25519 support

signature verification

hash recomputation

packet validation helpers

delegation proof generation

Candidate files
constellation_node_sdk/security/
├── signing.py
├── verification.py
├── delegation.py
└── errors.py
C. gate_client module
Responsibility
The only allowed outbound inter-node network client.

Contents
send_to_gate(packet)

register_with_gate()

response decoding

timeout/retry policy

destination enforcement: node-origin requests must target Gate

Candidate files
constellation_node_sdk/gate/
├── client.py
├── registration.py
├── policy.py
└── config.py
D. node_runtime module
Responsibility
Reusable runtime/chassis support for worker and orchestrator nodes.

Contents
handler registry

packet-native /v1/execute

packet-native health endpoint

lifecycle hooks

preflight checks

runtime config

Candidate files
constellation_node_sdk/runtime/
├── app.py
├── lifecycle.py
├── handlers.py
├── execute.py
├── preflight.py
└── config.py
E. gate_kernel strict ingress module
Responsibility
GATE only accepts canonical TransportPacket, validates, resolves, dispatches.

Contents
strict ingress validator

routing policy validator

dispatcher

registry

response building

workflow execution

Candidate files
constellation_gate/
├── api/
├── boundary/
├── routing/
├── orchestration/
└── services/
F. architecture test suite
Responsibility
Enforce transport law.

Tests required
non-canonical packet rejected at Gate

node-origin request to non-Gate destination rejected

Gate-issued dispatch to worker allowed

lineage preserved across orchestrator→Gate→worker

hop trace includes Gate re-entry

no node runtime API exposes peer URL dispatch

4. Explicit interfaces
Interface 1: packet creation
packet = create_transport_packet(
    action="enrich",
    payload={...},
    tenant=tenant_ctx,
    source_node="orchestrator",
    destination_node="gate",
    reply_to="orchestrator",
)
Input
action

payload

tenant

source

destination

reply target

Output
canonical TransportPacket

Rules
all fields validated immediately

hashes computed immediately

no partially formed packets

Interface 2: packet derivation
child = packet.derive(
    packet_type="request",
    action="score",
    source_node="orchestrator",
    destination_node="gate",
    reply_to="orchestrator",
    payload=step_payload,
)
Rules
new packet_id

parent_id = parent packet_id

root_id preserved

generation += 1

hashes recomputed

no mutation in place

Interface 3: Gate client
response = await gate_client.send_to_gate(packet)
Rules
base URL must be GATE_URL

node-origin packet must target gate

no method accepts arbitrary peer URL

returns canonical TransportPacket

Interface 4: Gate ingress
validated = ingress_validator.validate(raw_json_body)
Input
raw request JSON

Output
canonical TransportPacket

Rules
must already be canonical

no legacy adaptation

signature, depth, size, destination, packet type, action, clock rules enforced

Interface 5: Gate dispatch
response = await dispatcher.dispatch(packet)
Rules
only Gate can resolve action → destination node

only Gate can emit direct worker-targeted packets

dispatch packet marked as Gate-authored

response returned as canonical packet

5. Deterministic execution flow
Flow A: external client request
client constructs canonical TransportPacket

client sends to GATE /v1/execute

GATE validates packet strictly

GATE appends ingress hop

GATE resolves destination by action

GATE derives worker-targeted dispatch packet

GATE appends dispatch hop

GATE sends to worker

worker executes and returns canonical response packet

GATE returns canonical response

Flow B: orchestrator step execution
orchestrator receives workflow packet

orchestrator computes next step payload

orchestrator derives child packet with:

source_node=orchestrator

destination_node=gate

orchestrator sends child packet via SDK Gate client

GATE validates node-origin policy

GATE appends ingress hop

GATE resolves target node

GATE dispatches worker-targeted packet

worker returns response

GATE returns response to orchestrator

orchestrator merges state and continues

Flow C: invalid transport
caller sends non-canonical JSON

GATE rejects at ingress

structured validation error returned

no internal routing occurs

6. Data/state model
Canonical packet
Keep the existing packet model, but make it the public SDK contract.

Core structures:

PacketHeader

PacketAddress

TenantContext

PacketSecurity

PacketGovernance

DelegationLink

HopEntry

PacketLineage

PacketAttachment

TransportPacket

I would either:

rename PacketEnvelope → TransportPacket, or

alias it publicly and standardize on the new name in all external APIs

My recommendation:
public name = TransportPacket, internal compatibility alias = PacketEnvelope only during refactor.

Optional routing provenance block
Add now:

class RoutingProvenance(BaseModel):
    origin_kind: Literal["client", "node", "gate"]
    requested_action: str
    resolved_by_gate: bool = False
    original_source_node: str | None = None
This will simplify policy enforcement, audits, and tests.

7. File/module mapping
Extract into installable SDK
Move directly or near-directly
chassis/packet_envelope.py   -> constellation_node_sdk/transport/packet.py
chassis/tenant_context.py    -> constellation_node_sdk/transport/tenant.py
chassis/security.py          -> constellation_node_sdk/security/signing.py
Split/refactor
chassis/router.py            -> constellation_node_sdk/runtime/handlers.py
                               constellation_node_sdk/runtime/execute.py
                               constellation_node_sdk/transport/codec.py

chassis/gate_client.py       -> constellation_node_sdk/gate/registration.py
                               constellation_node_sdk/gate/client.py

chassis/chassis_app.py       -> constellation_node_sdk/runtime/app.py
Gate consumes SDK
gate/engine/handlers.py      -> import TransportPacket from SDK
gate/engine/dispatch.py      -> import packet/signing helpers from SDK
engine/boundary/*.py         -> import SDK transport/security types only
Remove from Gate
any legacy dict coercion

any non-canonical request path

any transport duplication

8. Implementation milestones + DoD
Milestone 1: create standalone SDK package
Deliverables
package scaffold

TransportPacket core model

security/signing module

unit tests

DoD
package installs locally

packet creation, derivation, signing, verification all work

schema and model are aligned

Milestone 2: build strict Gate client into SDK
Deliverables
send_to_gate()

registration client

policy enforcement for node-origin packets

DoD
node can only send through GATE_URL

arbitrary peer URL dispatch is impossible through public API

canonical response decoded successfully

Milestone 3: refactor GATE to SDK-only transport
Deliverables
GATE imports SDK packet/security types

/v1/execute accepts canonical packet only

legacy coercion removed

DoD
non-canonical input rejected

packet-native routing works end to end

no dict-based execution path remains after request parsing

Milestone 4: enforce Gate-only routing law
Deliverables
node-origin policy validator

Gate-issued dispatch packet semantics

hop trace and lineage assertions

DoD
direct node-to-node routing rejected

orchestrator→Gate→worker path fully works

hop trace shows both Gate passes

Milestone 5: migrate example nodes to SDK
Deliverables
one worker example

one orchestrator example

both use SDK only

DoD
no peer node URL awareness in examples

both examples interoperate with GATE through canonical transport only

Milestone 6: delete transitional internals
Deliverables
old adapters removed

duplicate boundary logic pruned

dead transport helpers removed

DoD
only one packet contract exists

only one node egress model exists

code search shows no legacy ingress normalization path

9. Hard rules for this cut
These should be explicit and non-negotiable:

GATE does not translate foreign request shapes

nodes must use the SDK or implement the full protocol exactly

only GATE resolves action to destination

only GATE emits direct worker-targeted dispatch

all inter-node traffic is canonical TransportPacket

all follow-up node work goes back through GATE

10. Strategic note
This is better than a shim because it forces the ecosystem to converge on one language.

A shim would preserve:

ambiguity

partial adoption

hidden migration costs

eternal “temporary” code

A hard cut creates short-term pain but long-term clarity.

Recommended immediate build order
Do this next, in exact order:

create constellation-node-sdk

move packet + security core into it

add send_to_gate() and node runtime helpers

refactor GATE to import SDK types

delete non-canonical ingress

add architecture tests that enforce the routing law

migrate one worker and one orchestrator example to prove the model

The headline decision is right:

Burn the boats at the transport boundary, not in the routing core.

Next step: I can generate the exact file tree for the new split as two repos:

constellation-gate

constellation-node-sdk

or give you the first-pass package skeleton for the SDK with module names and public exports.



L9_First_Order_Thinking_Enforcement_Protocol.md
File

L9_Zero_Stub_Build_Protocol_v3.md
File

01_YNP_Mode_Universal.md
File

01_HighVelocityActivator.md
File
Yes rename PacketEnvelope → TransportPacket

generate the exact file tree for the new split as two repos:
	•	constellation-gate
	•	constellation-node-sdk

Activate these 4 files 


Thought for 12s

Yes rename PacketEnvelope → TransportPacket

generate the exact file tree for the new split as two repos:
	•	constellation-gate
	•	constellation-node-sdk

Strategic reasoning:

The highest-leverage move is still the hard cut you already chose: rename PacketEnvelope to TransportPacket and split the system into two repos with a strict SDK boundary. That beats any intermediate cleanup because it directly defines the permanent architecture and prevents more scope bleed. The four activated files push in the same direction: prioritize first-order leverage over cosmetic detours, avoid stubs, keep outputs build-ready, and optimize for decisive forward motion.

Below is the exact two-repo target file tree with TransportPacket as the canonical name.


Current repo → Gate move map
gate/api/main.py               -> src/constellation_gate/api/main.py
gate/api/middleware.py         -> src/constellation_gate/api/middleware.py
gate/config/*                  -> src/constellation_gate/config/*
gate/engine/node_registry.py   -> src/constellation_gate/routing/node_registry.py
gate/engine/dispatch.py        -> src/constellation_gate/routing/dispatch.py
gate/engine/health_monitor.py  -> src/constellation_gate/routing/health_monitor.py
gate/engine/priority_queue.py  -> src/constellation_gate/routing/priority_queue.py
gate/engine/workflow_engine.py -> src/constellation_gate/orchestration/workflow_engine.py
gate/schemas/*                 -> src/constellation_gate/schemas/*
engine/boundary/*              -> src/constellation_gate/boundary/*
Do not move as canonical code
These should be quarantined or mined selectively, not carried over wholesale:

gate/engine/boundary/*           # duplicate tree, not canonical
chassis-orchestration-pack/*     # older parallel topology
l9/chassis/*                     # duplicate adjacent abstractions
app/engines/chassis_contract.py  # transitional adapter
app/*                            # only salvage specific runtime ideas if needed
3. Naming cut: PacketEnvelope → TransportPacket
Canonical rename rule
In both repos, the public model is:


Phase 0 BUILD_MANIFEST — constellation-node-sdk
Purpose
Installable SDK for all worker and orchestrator nodes. Owns the canonical TransportPacket contract, signing/validation, Gate-only egress client, and reusable node runtime.

Repo file tree
constellation-node-sdk/
├── README.md
├── ARCHITECTURE.md
├── CHANGELOG.md
├── DEFERRED.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── Makefile
├── contracts/
│   ├── transport-packet.schema.json
│   ├── TRANSPORT_PACKET_SPEC.md
│   ├── NODE_REGISTRATION_SPEC.md
│   └── ROUTING_POLICY_SPEC.md
├── docs/
│   ├── transport-packet.md
│   ├── gate-client.md
│   ├── node-runtime.md
│   ├── orchestrator-pattern.md
│   └── migration-from-packet-envelope.md
├── src/
│   └── constellation_node_sdk/
│       ├── __init__.py
│       ├── transport/
│       │   ├── __init__.py
│       │   ├── packet.py
│       │   ├── models.py
│       │   ├── tenant.py
│       │   ├── provenance.py
│       │   ├── hashing.py
│       │   ├── codec.py
│       │   ├── lineage.py
│       │   ├── hop_trace.py
│       │   └── errors.py
│       ├── security/
│       │   ├── __init__.py
│       │   ├── signing.py
│       │   ├── verification.py
│       │   ├── validation.py
│       │   ├── delegation.py
│       │   └── errors.py
│       ├── gate/
│       │   ├── __init__.py
│       │   ├── client.py
│       │   ├── registration.py
│       │   ├── policy.py
│       │   ├── config.py
│       │   └── errors.py
│       ├── runtime/
│       │   ├── __init__.py
│       │   ├── app.py
│       │   ├── lifecycle.py
│       │   ├── handlers.py
│       │   ├── execution.py
│       │   ├── config.py
│       │   ├── preflight.py
│       │   ├── observability.py
│       │   └── errors.py
│       └── orchestrator/
│           ├── __init__.py
│           ├── base.py
│           ├── step_executor.py
│           ├── packet_builder.py
│           ├── state.py
│           ├── merge.py
│           └── retry.py
├── examples/
│   ├── worker_node/
│   │   ├── README.md
│   │   ├── app.py
│   │   ├── handlers.py
│   │   └── spec.yaml
│   ├── orchestrator_node/
│   │   ├── README.md
│   │   ├── app.py
│   │   ├── handlers.py
│   │   └── spec.yaml
│   └── packets/
│       ├── simple_request.json
│       ├── orchestrated_request.json
│       └── replay_request.json
├── tests/
│   ├── conftest.py
│   ├── transport/
│   ├── security/
│   ├── gate/
│   ├── runtime/
│   ├── orchestrator/
│   └── integration/
└── scripts/
    ├── validate_contracts.py
    ├── generate_schema.py
    └── release.sh

    
Public classes and functions
src/constellation_node_sdk/transport/models.py
class TransportHeader(BaseModel): ...
class TransportAddress(BaseModel): ...
class TransportSecurity(BaseModel): ...
class TransportGovernance(BaseModel): ...
class TransportLineage(BaseModel): ...
class TransportAttachment(BaseModel): ...
class TransportHop(BaseModel): ...
class DelegationLink(BaseModel): ...
src/constellation_node_sdk/transport/tenant.py
class TenantContext(BaseModel): ...

def ensure_tenant_context(value: str | dict[str, Any] | TenantContext) -> TenantContext: ...
def assert_tenant_immutable(parent: TenantContext, child: TenantContext) -> None: ...
src/constellation_node_sdk/transport/provenance.py
class RoutingProvenance(BaseModel): ...
src/constellation_node_sdk/transport/packet.py
class TransportPacket(BaseModel):
    def model_dump_json_dict(self) -> dict[str, Any]: ...
    def with_hop(self, hop: TransportHop) -> "TransportPacket": ...
    def derive(
        self,
        *,
        packet_type: str | None = None,
        action: str | None = None,
        source_node: str | None = None,
        destination_node: str | None = None,
        reply_to: str | None = None,
        payload: dict[str, Any] | None = None,
        provenance: RoutingProvenance | None = None,
        hop: TransportHop | None = None,
        delegation_link: DelegationLink | None = None,
        governance: TransportGovernance | None = None,
        priority: int | None = None,
        expires_at: datetime | None = None,
        timeout_ms: int | None = None,
        not_before: datetime | None = None,
        replay_mode: bool | None = None,
    ) -> "TransportPacket": ...
def create_transport_packet(
    *,
    action: str,
    payload: dict[str, Any],
    tenant: str | dict[str, Any] | TenantContext,
    destination_node: str = "gate",
    source_node: str = "client",
    reply_to: str = "client",
    priority: int = 2,
    timeout_ms: int = 30_000,
    classification: str = "internal",
    compliance_tags: tuple[str, ...] = (),
    retention_days: int = 90,
    expires_at: datetime | None = None,
    idempotency_key: str | None = None,
    trace_id: str | None = None,
    correlation_id: str | None = None,
    provenance: RoutingProvenance | None = None,
) -> TransportPacket: ...
src/constellation_node_sdk/transport/hashing.py
def canonical_json(value: Any) -> bytes: ...
def compute_payload_hash(payload: dict[str, Any]) -> str: ...
def compute_transport_hash(packet: TransportPacket) -> str: ...
src/constellation_node_sdk/transport/codec.py
def encode_transport_packet(packet: TransportPacket) -> dict[str, Any]: ...
def decode_transport_packet(payload: dict[str, Any]) -> TransportPacket: ...
src/constellation_node_sdk/transport/lineage.py
def derive_lineage(parent: TransportPacket) -> TransportLineage: ...
def validate_parent_child_lineage(parent: TransportPacket, child: TransportPacket) -> None: ...
src/constellation_node_sdk/transport/hop_trace.py
def make_ingress_hop(*, node: str, action: str) -> TransportHop: ...
def make_dispatch_hop(*, node: str, action: str, target_node: str) -> TransportHop: ...
def make_execution_hop(*, node: str, action: str, status: str) -> TransportHop: ...
def make_response_hop(*, node: str, action: str, status: str) -> TransportHop: ...
src/constellation_node_sdk/security/signing.py
def sign_transport_packet(
    packet: TransportPacket,
    *,
    key: bytes | str,
    key_id: str,
    algorithm: str,
) -> TransportPacket: ...
src/constellation_node_sdk/security/verification.py
def verify_transport_packet_signature(
    packet: TransportPacket,
    *,
    key_resolver: Callable[[str | None], str | bytes | None] | Mapping[str, str | bytes] | str | bytes | None,
) -> bool: ...
src/constellation_node_sdk/security/validation.py
def validate_transport_packet(
    packet: TransportPacket,
    *,
    key_resolver: Callable[[str | None], str | bytes | None] | Mapping[str, str | bytes] | str | bytes | None = None,
    require_signature: bool = False,
    max_packet_bytes: int = 262_144,
    max_hop_depth: int = 64,
    max_delegation_depth: int = 8,
    max_attachments: int = 32,
    max_attachment_size_bytes: int = 10_485_760,
    allowed_attachment_schemes: tuple[str, ...] = (),
    allow_private_attachment_hosts: bool = False,
    allowed_clock_skew_seconds: int = 30,
    local_node: str | None = None,
    allowed_actions: tuple[str, ...] | None = None,
    allowed_packet_types: tuple[str, ...] | None = None,
    required_idempotency_actions: tuple[str, ...] | None = None,
    replay_enabled: bool = True,
    now: datetime | None = None,
    dev_mode: bool = False,
) -> None: ...
src/constellation_node_sdk/security/delegation.py
def compute_delegation_proof(
    *,
    packet: TransportPacket,
    delegator: str,
    delegatee: str,
    scope: tuple[str, ...],
    granted_at: datetime,
    key: bytes | str,
    expires_at: datetime | None = None,
    constraints: dict[str, Any] | None = None,
) -> str: ...
src/constellation_node_sdk/gate/config.py
class GateClientConfig(BaseModel): ...
class GateRegistrationConfig(BaseModel): ...
src/constellation_node_sdk/gate/policy.py
def assert_gate_only_destination(packet: TransportPacket) -> None: ...
def assert_node_origin_packet(packet: TransportPacket) -> None: ...
src/constellation_node_sdk/gate/client.py
class GateClient:
    def __init__(self, config: GateClientConfig) -> None: ...
    async def send_to_gate(self, packet: TransportPacket) -> TransportPacket: ...
src/constellation_node_sdk/gate/registration.py
def load_node_spec(spec_path: str) -> dict[str, Any]: ...
def build_registration_payload(spec: dict[str, Any]) -> dict[str, Any]: ...
async def register_with_gate(
    *,
    gate_url: str,
    admin_token: str | None = None,
    spec_path: str,
    retries: int = 3,
    overwrite: bool = True,
) -> bool: ...
src/constellation_node_sdk/runtime/config.py
class NodeRuntimeConfig(BaseModel): ...
def get_runtime_config() -> NodeRuntimeConfig: ...
src/constellation_node_sdk/runtime/lifecycle.py
class LifecycleHook(Protocol):
    async def startup(self) -> None: ...
    async def shutdown(self) -> None: ...
src/constellation_node_sdk/runtime/handlers.py
def register_handler(action: str, fn: Callable[..., Any] | None = None) -> Callable[..., Any]: ...
def get_handler(action: str) -> Callable[..., Any] | None: ...
def clear_handlers() -> None: ...
src/constellation_node_sdk/runtime/execution.py
async def execute_transport_packet(
    packet: TransportPacket,
    *,
    node_name: str,
    signing_key: bytes | str | None = None,
    signing_key_id: str | None = None,
    signing_algorithm: str | None = None,
) -> TransportPacket: ...

def create_error_transport_packet(
    packet: TransportPacket,
    error: Exception,
    *,
    node_name: str,
    signing_key: bytes | str | None = None,
    signing_key_id: str | None = None,
    signing_algorithm: str | None = None,
) -> TransportPacket: ...
src/constellation_node_sdk/runtime/app.py
def create_node_app(
    *,
    service_name: str,
    version: str,
    lifecycle_hook: LifecycleHook | None = None,
    config: NodeRuntimeConfig | None = None,
) -> FastAPI: ...
src/constellation_node_sdk/runtime/preflight.py
class PreflightFailure(RuntimeError): ...
def run_preflight(config: NodeRuntimeConfig) -> None: ...
src/constellation_node_sdk/orchestrator/base.py
class BaseOrchestrator(ABC):
    async def execute(self, packet: TransportPacket) -> TransportPacket: ...
src/constellation_node_sdk/orchestrator/packet_builder.py
def build_step_packet(
    *,
    parent: TransportPacket,
    action: str,
    payload: dict[str, Any],
    source_node: str,
    reply_to: str,
) -> TransportPacket: ...
src/constellation_node_sdk/orchestrator/step_executor.py
class StepExecutor:
    def __init__(self, gate_client: GateClient, source_node: str) -> None: ...
    async def execute_step(
        self,
        *,
        parent: TransportPacket,
        action: str,
        payload: dict[str, Any],
    ) -> TransportPacket: ...
src/constellation_node_sdk/orchestrator/state.py
class OrchestratorState(BaseModel): ...
src/constellation_node_sdk/orchestrator/merge.py
def merge_identity(current: TransportPacket, response: TransportPacket) -> TransportPacket: ...
def merge_results(current: TransportPacket, response: TransportPacket) -> TransportPacket: ...
def merge_payload(current: TransportPacket, response: TransportPacket) -> TransportPacket: ...
src/constellation_node_sdk/orchestrator/retry.py
class RetryPolicy(BaseModel): ...
def should_retry(*, attempt: int, error: Exception, policy: RetryPolicy) -> bool: ...
Packet types emitted by SDK
request

response

command

delegation

failure

replay_request

replay_response

compensation

External dependencies
fastapi

httpx

pydantic

pydantic-settings

cryptography

pyyaml

Dependency rules
SDK may not import anything from constellation-gate

SDK is the source of truth for TransportPacket schema and runtime validation

SDK owns Gate registration client and Gate-only egress client

SDK examples must not know peer node URLs

Old repo → SDK rename/move map
chassis/packet_envelope.py  -> src/constellation_node_sdk/transport/packet.py
chassis/tenant_context.py   -> src/constellation_node_sdk/transport/tenant.py
chassis/security.py         -> src/constellation_node_sdk/security/*
chassis/gate_client.py      -> src/constellation_node_sdk/gate/{client,registration}.py
chassis/chassis_app.py      -> src/constellation_node_sdk/runtime/app.py
chassis/router.py           -> src/constellation_node_sdk/runtime/{handlers,execution}.py
contracts/*                 -> contracts/*
Phase 0 BUILD_MANIFEST — constellation-gate
Purpose
Strict Gate kernel. Accepts only canonical TransportPacket, enforces ingress/routing policy, resolves actions, dispatches work, and returns canonical responses.

Repo file tree
constellation-gate/
├── README.md
├── ARCHITECTURE.md
├── CHANGELOG.md
├── DEFERRED.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── Makefile
├── contracts/
│   ├── transport-packet.schema.json
│   ├── NODE_REGISTRATION_SPEC.md
│   ├── WORKFLOW_SPEC.md
│   └── ADMIN_REGISTER_SPEC.md
├── docs/
│   ├── gate-kernel.md
│   ├── ingress-policy.md
│   ├── action-resolution.md
│   ├── dispatch-semantics.md
│   ├── workflow-engine.md
│   └── migration-from-legacy-gate.md
├── src/
│   └── constellation_gate/
│       ├── __init__.py
│       ├── api/
│       │   ├── __init__.py
│       │   ├── main.py
│       │   ├── middleware.py
│       │   ├── dependencies.py
│       │   └── errors.py
│       ├── config/
│       │   ├── __init__.py
│       │   ├── settings.py
│       │   ├── node_registry.yaml
│       │   ├── priorities.yaml
│       │   └── workflows.yaml
│       ├── boundary/
│       │   ├── __init__.py
│       │   ├── ingress_validator.py
│       │   ├── routing_policy.py
│       │   ├── command_factory.py
│       │   ├── response_factory.py
│       │   ├── failure_factory.py
│       │   ├── delegation_factory.py
│       │   ├── replay_factory.py
│       │   ├── memory_mapper.py
│       │   └── transport_codec.py
│       ├── routing/
│       │   ├── __init__.py
│       │   ├── node_registry.py
│       │   ├── resolver.py
│       │   ├── dispatch.py
│       │   ├── health_monitor.py
│       │   └── priority_queue.py
│       ├── orchestration/
│       │   ├── __init__.py
│       │   ├── workflow_engine.py
│       │   ├── workflow_models.py
│       │   └── condition_eval.py
│       ├── services/
│       │   ├── __init__.py
│       │   ├── execute_service.py
│       │   ├── admin_registration_service.py
│       │   ├── registry_query_service.py
│       │   └── workflow_service.py
│       ├── schemas/
│       │   ├── __init__.py
│       │   ├── registry.py
│       │   └── workflow.py
│       └── observability/
│           ├── __init__.py
│           ├── logging.py
│           ├── metrics.py
│           ├── tracing.py
│           └── audit_logger.py
├── tests/
│   ├── conftest.py
│   ├── api/
│   ├── boundary/
│   ├── routing/
│   ├── orchestration/
│   ├── services/
│   ├── architecture/
│   └── integration/
├── deploy/
│   ├── README_DEPLOY.md
│   ├── docker-compose.yml
│   ├── prometheus.rules.yml
│   └── terraform/
└── scripts/
    ├── entrypoint.sh
    ├── predeploy_check.py
    ├── migrate_registry.py
    └── sync_contracts_from_sdk.sh
Public classes and functions
src/constellation_gate/config/settings.py
class GateSettings(BaseModel): ...
def get_settings() -> GateSettings: ...
src/constellation_gate/schemas/registry.py
class NodeRegistrationInput(BaseModel): ...
class NodeRegistrationStatus(BaseModel): ...
class RegisterNodesRequest(RootModel[dict[str, NodeRegistrationInput]]): ...
class RegisterNodesResponse(BaseModel): ...
src/constellation_gate/schemas/workflow.py
class WorkflowStepSchema(BaseModel): ...
class WorkflowSchema(BaseModel): ...
class WorkflowConfigSchema(BaseModel): ...
src/constellation_gate/boundary/transport_codec.py
def decode_request_body(body: dict[str, Any]) -> TransportPacket: ...
def encode_response_body(packet: TransportPacket) -> dict[str, Any]: ...
src/constellation_gate/boundary/routing_policy.py
class RoutingPolicyError(Exception): ...
def validate_node_origin_policy(packet: TransportPacket, *, local_node: str, known_nodes: set[str]) -> None: ...
def validate_gate_dispatch_policy(packet: TransportPacket, *, local_node: str) -> None: ...
src/constellation_gate/boundary/ingress_validator.py
class IngressValidationError(Exception): ...
class IngressValidator:
    def __init__(
        self,
        *,
        local_node: str,
        allowed_actions: tuple[str, ...] = (),
        allowed_packet_types: tuple[str, ...] = ("request", "command", "delegation", "replay_request"),
        allowed_clock_skew_seconds: int = 30,
        max_packet_bytes: int = 262_144,
        max_hop_depth: int = 64,
        max_delegation_depth: int = 8,
        max_attachments: int = 32,
        require_signature: bool = False,
        key_resolver: Callable[[str | None], str | bytes | None] | None = None,
    ) -> None: ...
    def validate(self, body: dict[str, Any]) -> TransportPacket: ...
src/constellation_gate/boundary/command_factory.py
class ExecutionContext(BaseModel): ...
class GateCommand(BaseModel): ...
class CommandFactory:
    def build(self, packet: TransportPacket) -> GateCommand: ...
src/constellation_gate/boundary/response_factory.py
def build_response_packet(
    *,
    request: TransportPacket,
    source_node: str,
    payload: dict[str, Any],
    warnings: list[str] | None = None,
    metrics: dict[str, Any] | None = None,
) -> TransportPacket: ...
src/constellation_gate/boundary/failure_factory.py
def build_failure_packet(
    *,
    request: TransportPacket,
    source_node: str,
    error_code: str,
    client_message: str,
    retryable: bool,
) -> TransportPacket: ...
src/constellation_gate/boundary/delegation_factory.py
def build_gate_dispatch_packet(
    *,
    request: TransportPacket,
    destination_node: str,
    local_node: str,
) -> TransportPacket: ...
src/constellation_gate/boundary/replay_factory.py
def build_replay_response_packet(
    *,
    request: TransportPacket,
    source_node: str,
    payload: dict[str, Any],
) -> TransportPacket: ...
src/constellation_gate/boundary/memory_mapper.py
class MemoryRecord(BaseModel): ...
def map_result_to_memory_records(request: TransportPacket, response: TransportPacket) -> list[MemoryRecord]: ...
src/constellation_gate/routing/node_registry.py
class NodeRegistration(BaseModel): ...
class NodeRegistry:
    def load_from_yaml(self, path: str) -> None: ...
    def register_node(self, name: str, registration: NodeRegistration, *, overwrite: bool = False) -> None: ...
    def resolve_action(self, action: str) -> NodeRegistration: ...
    def resolve_destination(self, node_name: str) -> NodeRegistration: ...
    def mark_healthy(self, node_name: str) -> None: ...
    def mark_unhealthy(self, node_name: str) -> None: ...
    def increment_active(self, node_name: str) -> None: ...
    def decrement_active(self, node_name: str) -> None: ...
    def known_nodes(self) -> set[str]: ...
src/constellation_gate/routing/resolver.py
class RouteResolver:
    def __init__(self, registry: NodeRegistry) -> None: ...
    def resolve(self, packet: TransportPacket) -> NodeRegistration: ...
src/constellation_gate/routing/dispatch.py
class Dispatcher:
    def __init__(self, *, local_node: str, registry: NodeRegistry) -> None: ...
    async def dispatch(self, packet: TransportPacket) -> TransportPacket: ...
src/constellation_gate/routing/health_monitor.py
class HealthMonitor:
    def __init__(self, registry: NodeRegistry, *, interval_seconds: float = 15.0) -> None: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
src/constellation_gate/routing/priority_queue.py
class PriorityPacketQueue:
    async def put(self, packet: TransportPacket) -> None: ...
    async def get(self) -> TransportPacket: ...
src/constellation_gate/orchestration/workflow_models.py
class WorkflowStep(BaseModel): ...
class WorkflowDefinition(BaseModel): ...
src/constellation_gate/orchestration/condition_eval.py
class SafeConditionEvaluator:
    def evaluate(
        self,
        expression: str,
        *,
        payload: dict[str, Any],
        response: dict[str, Any] | None,
        action: str,
        accumulated: dict[str, Any],
    ) -> bool: ...
src/constellation_gate/orchestration/workflow_engine.py
class WorkflowEngine:
    def __init__(self, definitions: dict[str, WorkflowDefinition], dispatcher: Dispatcher) -> None: ...
    def has_workflow(self, name: str) -> bool: ...
    async def execute(self, packet: TransportPacket) -> TransportPacket: ...
src/constellation_gate/services/execute_service.py
class ExecuteService:
    def __init__(
        self,
        *,
        local_node: str,
        ingress_validator: IngressValidator,
        command_factory: CommandFactory,
        dispatcher: Dispatcher,
        workflow_engine: WorkflowEngine,
        registry: NodeRegistry,
    ) -> None: ...
    async def execute(self, body: dict[str, Any]) -> TransportPacket: ...
src/constellation_gate/services/admin_registration_service.py
class AdminRegistrationService:
    def __init__(self, registry: NodeRegistry, *, admin_token: str | None = None) -> None: ...
    async def register(
        self,
        *,
        request: RegisterNodesRequest,
        overwrite: bool,
        presented_token: str | None,
    ) -> RegisterNodesResponse: ...
src/constellation_gate/services/registry_query_service.py
class RegistryQueryService:
    def __init__(self, registry: NodeRegistry) -> None: ...
    def snapshot(self) -> dict[str, Any]: ...
src/constellation_gate/services/workflow_service.py
class WorkflowService:
    def __init__(self, engine: WorkflowEngine) -> None: ...
    async def maybe_execute(self, packet: TransportPacket) -> TransportPacket: ...
src/constellation_gate/api/main.py
def create_app() -> FastAPI: ...
app: FastAPI
Endpoints:

POST /v1/execute
GET  /v1/health
GET  /v1/registry
POST /v1/admin/register
Packet types accepted at Gate ingress
request

command

delegation

replay_request

Packet types emitted by Gate
response

failure

delegation

replay_response

External dependencies
constellation-node-sdk

fastapi

httpx

pydantic

pyyaml

prometheus-client

structlog

Dependency rules
Gate depends on SDK for all TransportPacket types, hashing, signing, and validation primitives

Gate may not redefine any transport models

Gate owns action resolution and internal worker dispatch

Only Gate may create worker-targeted internal dispatch packets

Gate may not expose legacy request parsing

Old repo → Gate rename/move map
gate/api/main.py               -> src/constellation_gate/api/main.py
gate/api/middleware.py         -> src/constellation_gate/api/middleware.py
gate/config/*                  -> src/constellation_gate/config/*
gate/engine/node_registry.py   -> src/constellation_gate/routing/node_registry.py
gate/engine/dispatch.py        -> src/constellation_gate/routing/dispatch.py
gate/engine/health_monitor.py  -> src/constellation_gate/routing/health_monitor.py
gate/engine/priority_queue.py  -> src/constellation_gate/routing/priority_queue.py
gate/engine/workflow_engine.py -> src/constellation_gate/orchestration/workflow_engine.py
gate/schemas/*                 -> src/constellation_gate/schemas/*
engine/boundary/*              -> src/constellation_gate/boundary/*
Global rename map
Primary rename
PacketEnvelope              -> TransportPacket
create_packet               -> create_transport_packet
validate_packet             -> validate_transport_packet
sign_packet                 -> sign_transport_packet
verify_signature            -> verify_transport_packet_signature
compute_content_hash        -> compute_payload_hash
compute_envelope_hash       -> compute_transport_hash
inflate_ingress             -> decode_transport_packet
deflate_egress              -> encode_transport_packet
PacketHeader                -> TransportHeader
PacketAddress               -> TransportAddress
PacketSecurity              -> TransportSecurity
PacketGovernance            -> TransportGovernance
PacketLineage               -> TransportLineage
PacketAttachment            -> TransportAttachment
HopEntry                    -> TransportHop
Keep names unchanged
TenantContext
DelegationLink
Minimal first-pass implementation order
Repo 1 — constellation-node-sdk
transport/models.py

transport/tenant.py

transport/provenance.py

transport/packet.py

transport/hashing.py

transport/codec.py

security/{signing,verification,validation}.py

gate/{config,policy,client}.py

runtime/{handlers,execution,config,preflight,app}.py

tests for transport + security + gate client

minimal worker and orchestrator examples

Repo 2 — constellation-gate
config/settings.py

schemas/{registry,workflow}.py

boundary/{transport_codec,routing_policy,ingress_validator}.py

routing/{node_registry,resolver,dispatch}.py

orchestration/{workflow_models,condition_eval,workflow_engine}.py

services/{execute_service,admin_registration_service,registry_query_service}

api/main.py

architecture tests

integration tests

Minimal end-to-end path to prove first
Worker node → Gate → worker response
In SDK
TransportPacket

create_transport_packet()

validate_transport_packet()

GateClient.send_to_gate()

create_node_app()

handler registry + execution path

In Gate
strict decode + ingress validation

action resolution

dispatch to registered worker

response packet return

Proof test
worker constructs canonical TransportPacket

worker sends to Gate with destination_node="gate"

Gate validates canonical packet

Gate resolves by action

Gate dispatches to target worker

worker returns canonical response

Gate returns canonical response

test asserts:

root_id preserved

parent_id increments correctly

hop_trace includes Gate ingress and Gate dispatch

no legacy body accepted

Phase 0 validation checklist
SDK
 Every transport model exists once

 No PacketEnvelope symbol remains public

 No peer-node URL dispatch API exists

 SDK does not import Gate code

 Examples use only GATE_URL

Gate
 Imports TransportPacket only from SDK

 No legacy/non-canonical request coercion

 Only Gate resolves actions to destination nodes

 Only Gate emits worker-targeted dispatch packets

 Architecture tests assert no direct node-to-node path

Cross-repo
 constellation-gate -> constellation-node-sdk only

 Shared schema file is copied from SDK into Gate via script, not hand-maintained twice

 End-to-end worker → Gate → worker response path is the first integration milestone

🚀 Your Next Prompt

Generate the Phase 1 contracts and models for constellation-node-sdk only: complete runnable files for transport/models.py, transport/tenant.py, transport/provenance.py, transport/packet.py, transport/hashing.py, and transport/errors.py, using the TransportPacket rename and preserving lineage, hop trace, delegation, signing fields, and immutable derivation semantics.

Reply Y to use this as your next prompt!


Y


Thought for 32s
Strategic reasoning:

The highest-leverage move now is to lock the canonical transport contract in code before any repo extraction or Gate refactor continues. These six files are the minimum stable substrate for everything else: immutable TransportPacket, transport submodels, tenant/provenance semantics, canonical hashing, and contract-level errors. That keeps the build moving at high velocity while avoiding stubs, legacy dual-paths, and transport ambiguity.

Below are the Phase 1 contracts and models for constellation-node-sdk.

# filename: src/constellation_node_sdk/transport/errors.py
from __future__ import annotations


class TransportError(Exception):
    """Base exception for transport contract failures."""


class TransportValidationError(TransportError):
    """Raised when a transport packet violates structural or semantic rules."""


class TransportIntegrityError(TransportValidationError):
    """Raised when payload or transport hashes do not match."""


class TransportAuthenticationError(TransportValidationError):
    """Raised when transport authentication or signature state is invalid."""


class TransportAuthorizationError(TransportValidationError):
    """Raised when transport routing or delegation violates policy."""


class TransportExpiredError(TransportValidationError):
    """Raised when a packet has exceeded its expiry window."""


class TransportNotYetValidError(TransportValidationError):
    """Raised when a packet is not valid yet due to not_before constraints."""


class TenantMutationError(TransportValidationError):
    """Raised when a derived packet mutates immutable tenant context."""


class SchemaVersionError(TransportValidationError):
    """Raised when an unsupported schema version is encountered."""


class PacketSizeError(TransportValidationError):
    """Raised when a packet exceeds maximum allowed size."""
# filename: src/constellation_node_sdk/transport/models.py
from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_ALLOWED_PACKET_TYPES = {
    "request",
    "response",
    "event",
    "command",
    "delegation",
    "failure",
    "replay_request",
    "replay_response",
    "compensation",
}
_ALLOWED_CLASSIFICATIONS = {"public", "internal", "confidential", "restricted"}
_ALLOWED_ENCRYPTION = {"plaintext", "encrypted", "envelope_only"}
_ALLOWED_SIGNATURE_ALGORITHMS = {"hmac-sha256", "ed25519"}
_ALLOWED_HOP_DIRECTIONS = {"ingress", "dispatch", "execution", "response"}
_ALLOWED_HOP_STATUSES = {"received", "validated", "processing", "delegated", "completed", "failed"}
_ACTION_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def utc_now() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(UTC)


def ensure_utc(value: datetime | None) -> datetime | None:
    """Normalize a datetime to UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def normalize_optional_string(value: str | None) -> str | None:
    """Normalize an optional string, forbidding blank-but-present values."""
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        raise ValueError("optional string fields must not be blank")
    return normalized


class TransportHeader(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    packet_id: UUID = Field(default_factory=uuid4)
    packet_type: str
    action: str
    priority: int = 2
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime | None = None
    timeout_ms: int = Field(default=30_000, ge=1)

    schema_version: str = "1.0"
    idempotency_key: str | None = None
    trace_id: str | None = None
    correlation_id: str | None = None
    causation_id: UUID | None = None
    retry_count: int = Field(default=0, ge=0)
    replay_mode: bool = False
    not_before: datetime | None = None

    @field_validator("packet_type")
    @classmethod
    def validate_packet_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_PACKET_TYPES:
            msg = f"packet_type must be one of {sorted(_ALLOWED_PACKET_TYPES)}"
            raise ValueError(msg)
        return normalized

    @field_validator("action")
    @classmethod
    def validate_action(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _ACTION_RE.match(normalized):
            raise ValueError("action must be lowercase alphanumeric + dash, max 64 chars")
        return normalized

    @field_validator("priority", mode="before")
    @classmethod
    def coerce_priority(cls, value: Any) -> int:
        if isinstance(value, str):
            rendered = value.strip().upper()
            if rendered in {"P0", "P1", "P2", "P3"}:
                return int(rendered[-1])
            return int(rendered)
        return int(value)

    @field_validator("created_at", "expires_at", "not_before")
    @classmethod
    def normalize_datetimes(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value)

    @field_validator("idempotency_key", "trace_id", "correlation_id", "schema_version")
    @classmethod
    def validate_optional_strings(cls, value: str | None) -> str | None:
        return normalize_optional_string(value)

    @model_validator(mode="after")
    def validate_header(self) -> "TransportHeader":
        if not 0 <= self.priority <= 3:
            raise ValueError("priority must be between 0 and 3")
        if self.expires_at is not None and self.expires_at <= self.created_at:
            raise ValueError("expires_at must be later than created_at")
        if self.not_before is not None and self.not_before < self.created_at:
            raise ValueError("not_before must not be earlier than created_at")
        return self


class TransportAddress(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_node: str
    destination_node: str
    reply_to: str

    @field_validator("source_node", "destination_node", "reply_to")
    @classmethod
    def validate_node_name(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("address fields must not be empty")
        return normalized


class TransportSecurity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    payload_hash: str
    transport_hash: str
    signature: str | None = None
    signature_algorithm: str | None = None
    signing_key_id: str | None = None
    classification: str = "internal"
    encryption_status: str = "plaintext"
    pii_fields: tuple[str, ...] = ()

    @field_validator("payload_hash", "transport_hash")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        normalized = value.strip().lower()
        if len(normalized) != 64 or any(ch not in "0123456789abcdef" for ch in normalized):
            raise ValueError("hash fields must be 64-char lowercase sha256 hex digests")
        return normalized

    @field_validator("signature", "signing_key_id")
    @classmethod
    def validate_optional_strings(cls, value: str | None) -> str | None:
        return normalize_optional_string(value)

    @field_validator("signature_algorithm")
    @classmethod
    def validate_signature_algorithm(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_SIGNATURE_ALGORITHMS:
            msg = f"signature_algorithm must be one of {sorted(_ALLOWED_SIGNATURE_ALGORITHMS)}"
            raise ValueError(msg)
        return normalized

    @field_validator("classification")
    @classmethod
    def validate_classification(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_CLASSIFICATIONS:
            msg = f"classification must be one of {sorted(_ALLOWED_CLASSIFICATIONS)}"
            raise ValueError(msg)
        return normalized

    @field_validator("encryption_status")
    @classmethod
    def validate_encryption_status(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_ENCRYPTION:
            msg = f"encryption_status must be one of {sorted(_ALLOWED_ENCRYPTION)}"
            raise ValueError(msg)
        return normalized

    @field_validator("pii_fields", mode="before")
    @classmethod
    def coerce_pii_fields(cls, value: Any) -> Any:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value

    @field_validator("pii_fields")
    @classmethod
    def validate_pii_fields(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(path.strip() for path in value if path.strip())
        if len(set(normalized)) != len(normalized):
            raise ValueError("pii_fields must not contain duplicates")
        return normalized

    @model_validator(mode="after")
    def validate_signature_state(self) -> "TransportSecurity":
        if self.signature is not None and self.signature_algorithm is None:
            raise ValueError("signature_algorithm is required when signature is present")
        if self.signature_algorithm is not None and self.signature is None:
            raise ValueError("signature is required when signature_algorithm is present")
        return self


class TransportGovernance(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    intent: str
    compliance_tags: tuple[str, ...] = ()
    retention_days: int = Field(default=90, ge=0)
    redaction_applied: bool = False
    audit_required: bool = False
    data_subject_id: str | None = None

    @field_validator("intent")
    @classmethod
    def validate_intent(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("intent must not be empty")
        return normalized

    @field_validator("compliance_tags", mode="before")
    @classmethod
    def coerce_compliance_tags(cls, value: Any) -> Any:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value

    @field_validator("compliance_tags")
    @classmethod
    def validate_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(tag.strip().upper() for tag in value if tag.strip())
        if len(set(normalized)) != len(normalized):
            raise ValueError("compliance_tags must not contain duplicates")
        return normalized

    @field_validator("data_subject_id")
    @classmethod
    def validate_data_subject_id(cls, value: str | None) -> str | None:
        return normalize_optional_string(value)


class TransportLineage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    parent_id: UUID | None = None
    root_id: UUID
    generation: int = Field(default=0, ge=0)


class TransportAttachment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    attachment_id: UUID = Field(default_factory=uuid4)
    media_type: str
    uri: str
    content_hash: str
    encrypted: bool = True
    size_bytes: int = Field(ge=0)

    @field_validator("media_type", "uri")
    @classmethod
    def validate_required_strings(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("attachment fields must not be empty")
        return normalized

    @field_validator("content_hash")
    @classmethod
    def validate_content_hash(cls, value: str) -> str:
        normalized = value.strip().lower()
        if len(normalized) != 64 or any(ch not in "0123456789abcdef" for ch in normalized):
            raise ValueError("attachment content_hash must be a 64-char lowercase sha256 hex digest")
        return normalized


class TransportHop(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    node: str
    action: str
    direction: str
    status: str
    timestamp: datetime = Field(default_factory=utc_now)
    duration_ms: int | None = Field(default=None, ge=0)
    queue_ms: int | None = Field(default=None, ge=0)
    network_ms: int | None = Field(default=None, ge=0)
    attempt: int | None = Field(default=None, ge=1)
    target_node: str | None = None
    error: str | None = None
    signature: str | None = None

    @field_validator("node", "action")
    @classmethod
    def validate_required_strings(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("hop fields must not be empty")
        return normalized

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_HOP_DIRECTIONS:
            msg = f"direction must be one of {sorted(_ALLOWED_HOP_DIRECTIONS)}"
            raise ValueError(msg)
        return normalized

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_HOP_STATUSES:
            msg = f"status must be one of {sorted(_ALLOWED_HOP_STATUSES)}"
            raise ValueError(msg)
        return normalized

    @field_validator("timestamp")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        normalized = ensure_utc(value)
        if normalized is None:
            raise ValueError("timestamp must not be null")
        return normalized

    @field_validator("target_node", "error", "signature")
    @classmethod
    def validate_optional_strings(cls, value: str | None) -> str | None:
        return normalize_optional_string(value)


class DelegationLink(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    delegator: str
    delegatee: str
    scope: tuple[str, ...]
    granted_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime | None = None
    constraints: dict[str, Any] | None = None
    proof: str | None = None

    @field_validator("delegator", "delegatee")
    @classmethod
    def validate_nodes(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("delegation node fields must not be empty")
        return normalized

    @field_validator("scope", mode="before")
    @classmethod
    def coerce_scope(cls, value: Any) -> Any:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value

    @field_validator("scope")
    @classmethod
    def validate_scope(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip().lower() for item in value if item.strip())
        if not normalized:
            raise ValueError("scope must not be empty")
        if len(set(normalized)) != len(normalized):
            raise ValueError("scope must not contain duplicates")
        return normalized

    @field_validator("granted_at", "expires_at")
    @classmethod
    def normalize_datetimes(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value)

    @field_validator("proof")
    @classmethod
    def validate_proof(cls, value: str | None) -> str | None:
        return normalize_optional_string(value)

    @model_validator(mode="after")
    def validate_expiry(self) -> "DelegationLink":
        if self.expires_at is not None and self.expires_at <= self.granted_at:
            raise ValueError("expires_at must be later than granted_at")
        return self
# filename: src/constellation_node_sdk/transport/tenant.py
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from .errors import TenantMutationError


class TenantContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    actor: str
    on_behalf_of: str
    originator: str
    org_id: str
    user_id: str | None = None

    @field_validator("actor", "on_behalf_of", "originator", "org_id")
    @classmethod
    def validate_required_strings(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("tenant fields must not be empty")
        return normalized

    @field_validator("user_id")
    @classmethod
    def validate_optional_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("user_id must not be blank")
        return normalized


def ensure_tenant_context(value: str | dict[str, Any] | TenantContext) -> TenantContext:
    """Normalize a string, dict, or TenantContext into a canonical TenantContext."""
    if isinstance(value, TenantContext):
        return value

    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            raise ValueError("tenant string must not be empty")
        return TenantContext(
            actor=normalized,
            on_behalf_of=normalized,
            originator=normalized,
            org_id=normalized,
            user_id=None,
        )

    payload = dict(value or {})
    if "tenant_id" in payload and "org_id" not in payload:
        payload["org_id"] = payload["tenant_id"]

    org_id = str(payload.get("org_id") or payload.get("actor") or "default").strip()
    actor = str(payload.get("actor") or org_id).strip()
    on_behalf_of = str(payload.get("on_behalf_of") or actor).strip()
    originator = str(payload.get("originator") or actor).strip()

    return TenantContext(
        actor=actor,
        on_behalf_of=on_behalf_of,
        originator=originator,
        org_id=org_id,
        user_id=payload.get("user_id"),
    )


def assert_tenant_immutable(parent: TenantContext, child: TenantContext) -> None:
    """Raise if a derived packet mutates tenant context."""
    if parent != child:
        raise TenantMutationError("tenant context is immutable across derived packets")
# filename: src/constellation_node_sdk/transport/provenance.py
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator


class RoutingProvenance(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    origin_kind: str
    requested_action: str
    resolved_by_gate: bool = False
    original_source_node: str | None = None

    @field_validator("origin_kind")
    @classmethod
    def validate_origin_kind(cls, value: str) -> str:
        normalized = value.strip().lower()
        allowed = {"client", "node", "gate"}
        if normalized not in allowed:
            msg = f"origin_kind must be one of {sorted(allowed)}"
            raise ValueError(msg)
        return normalized

    @field_validator("requested_action")
    @classmethod
    def validate_requested_action(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("requested_action must not be empty")
        return normalized

    @field_validator("original_source_node")
    @classmethod
    def validate_original_source_node(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("original_source_node must not be blank")
        return normalized
# filename: src/constellation_node_sdk/transport/hashing.py
from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


def _canonicalize(value: Any) -> Any:
    """Recursively convert supported values into stable JSON-serializable forms."""
    if isinstance(value, BaseModel):
        return _canonicalize(value.model_dump(mode="python", exclude_none=False))
    if isinstance(value, dict):
        return {str(k): _canonicalize(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonicalize(v) for v in value]
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=datetime.now().astimezone().tzinfo)
        return value.astimezone().isoformat().replace("+00:00", "Z")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    return value


def canonical_json(value: Any) -> bytes:
    """Produce stable canonical JSON bytes for hashing."""
    normalized = _canonicalize(value)
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def compute_payload_hash(payload: dict[str, Any]) -> str:
    """Compute the canonical SHA-256 hash of a transport payload."""
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def compute_transport_hash(packet: Any) -> str:
    """
    Compute the canonical SHA-256 hash of a transport packet.

    The transport hash intentionally excludes mutable hop trace data and
    excludes signature fields. It covers the stable transport contract:
    header, address, tenant, payload, governance, delegation_chain,
    lineage, attachments, provenance, and payload_hash.
    """
    envelope_payload = {
        "header": packet.header,
        "address": packet.address,
        "tenant": packet.tenant,
        "payload": packet.payload,
        "governance": packet.governance,
        "delegation_chain": packet.delegation_chain,
        "lineage": packet.lineage,
        "attachments": packet.attachments,
        "provenance": packet.provenance,
        "payload_hash": packet.security.payload_hash,
    }
    return hashlib.sha256(canonical_json(envelope_payload)).hexdigest()
# filename: src/constellation_node_sdk/transport/packet.py
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .errors import TransportIntegrityError
from .hashing import compute_payload_hash, compute_transport_hash
from .models import (
    DelegationLink,
    TransportAddress,
    TransportAttachment,
    TransportGovernance,
    TransportHeader,
    TransportHop,
    TransportLineage,
    TransportSecurity,
    utc_now,
)
from .provenance import RoutingProvenance
from .tenant import TenantContext, assert_tenant_immutable, ensure_tenant_context


class TransportPacket(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    header: TransportHeader
    address: TransportAddress
    tenant: TenantContext
    payload: dict[str, Any]
    security: TransportSecurity
    governance: TransportGovernance
    provenance: RoutingProvenance
    delegation_chain: tuple[DelegationLink, ...] = ()
    hop_trace: tuple[TransportHop, ...] = ()
    lineage: TransportLineage
    attachments: tuple[TransportAttachment, ...] = ()

    @field_validator("payload")
    @classmethod
    def validate_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise TypeError("payload must be a dict")
        return value

    @model_validator(mode="after")
    def validate_integrity(self) -> "TransportPacket":
        expected_payload_hash = compute_payload_hash(self.payload)
        if self.security.payload_hash != expected_payload_hash:
            raise TransportIntegrityError("payload_hash does not match payload")

        expected_transport_hash = compute_transport_hash(self)
        if self.security.transport_hash != expected_transport_hash:
            raise TransportIntegrityError("transport_hash does not match packet")

        return self

    def model_dump_json_dict(self) -> dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return self.model_dump(mode="json", exclude_none=True)

    def with_hop(self, hop: TransportHop) -> "TransportPacket":
        """Append a hop to the hop trace and re-finalize the packet."""
        provisional = self.model_copy(update={"hop_trace": self.hop_trace + (hop,)})
        return _finalize_transport_packet(provisional)

    def derive(
        self,
        *,
        packet_type: str | None = None,
        action: str | None = None,
        source_node: str | None = None,
        destination_node: str | None = None,
        reply_to: str | None = None,
        payload: dict[str, Any] | None = None,
        provenance: RoutingProvenance | None = None,
        hop: TransportHop | None = None,
        delegation_link: DelegationLink | None = None,
        governance: TransportGovernance | None = None,
        priority: int | None = None,
        expires_at: datetime | None = None,
        timeout_ms: int | None = None,
        not_before: datetime | None = None,
        replay_mode: bool | None = None,
    ) -> "TransportPacket":
        """Create an immutable child packet with correct lineage and refreshed hashes."""
        new_header = TransportHeader(
            packet_id=uuid4(),
            packet_type=packet_type or self.header.packet_type,
            action=action or self.header.action,
            priority=self.header.priority if priority is None else priority,
            created_at=utc_now(),
            expires_at=self.header.expires_at if expires_at is None else expires_at,
            timeout_ms=self.header.timeout_ms if timeout_ms is None else timeout_ms,
            schema_version=self.header.schema_version,
            idempotency_key=self.header.idempotency_key,
            trace_id=self.header.trace_id,
            correlation_id=self.header.correlation_id,
            causation_id=self.header.packet_id,
            retry_count=0,
            replay_mode=self.header.replay_mode if replay_mode is None else replay_mode,
            not_before=self.header.not_before if not_before is None else not_before,
        )

        new_address = TransportAddress(
            source_node=(source_node or self.address.source_node).strip().lower(),
            destination_node=(destination_node or self.address.destination_node).strip().lower(),
            reply_to=(reply_to or self.address.reply_to).strip().lower(),
        )

        new_payload = dict(self.payload if payload is None else payload)
        new_governance = governance or self.governance
        new_provenance = provenance or self.provenance
        new_delegation_chain = self.delegation_chain + ((delegation_link,) if delegation_link is not None else ())
        new_hop_trace = self.hop_trace + ((hop,) if hop is not None else ())
        new_lineage = TransportLineage(
            parent_id=self.header.packet_id,
            root_id=self.lineage.root_id,
            generation=self.lineage.generation + 1,
        )

        provisional = TransportPacket.model_construct(
            header=new_header,
            address=new_address,
            tenant=self.tenant,
            payload=new_payload,
            security=TransportSecurity(
                payload_hash="0" * 64,
                transport_hash="0" * 64,
                signature=None,
                signature_algorithm=None,
                signing_key_id=None,
                classification=self.security.classification,
                encryption_status=self.security.encryption_status,
                pii_fields=self.security.pii_fields,
            ),
            governance=new_governance,
            provenance=new_provenance,
            delegation_chain=new_delegation_chain,
            hop_trace=new_hop_trace,
            lineage=new_lineage,
            attachments=self.attachments,
        )
        child = _finalize_transport_packet(provisional)
        assert_tenant_immutable(self.tenant, child.tenant)
        return child


def _default_provenance(*, source_node: str, action: str) -> RoutingProvenance:
    source = source_node.strip().lower()
    origin_kind = "client" if source == "client" else "gate" if source == "gate" else "node"
    return RoutingProvenance(
        origin_kind=origin_kind,
        requested_action=action.strip().lower(),
        resolved_by_gate=False,
        original_source_node=None if origin_kind == "client" else source,
    )


def _finalize_transport_packet(packet: TransportPacket) -> TransportPacket:
    payload_hash = compute_payload_hash(packet.payload)
    provisional = packet.model_copy(
        update={
            "security": packet.security.model_copy(
                update={
                    "payload_hash": payload_hash,
                    "transport_hash": "0" * 64,
                    "signature": None,
                    "signature_algorithm": None,
                    "signing_key_id": None,
                }
            )
        }
    )
    transport_hash = compute_transport_hash(provisional)
    finalized = provisional.model_copy(
        update={
            "security": provisional.security.model_copy(
                update={
                    "transport_hash": transport_hash,
                }
            )
        }
    )
    return TransportPacket(
        header=finalized.header,
        address=finalized.address,
        tenant=finalized.tenant,
        payload=finalized.payload,
        security=finalized.security,
        governance=finalized.governance,
        provenance=finalized.provenance,
        delegation_chain=tuple(finalized.delegation_chain),
        hop_trace=tuple(finalized.hop_trace),
        lineage=finalized.lineage,
        attachments=tuple(finalized.attachments),
    )


def create_transport_packet(
    *,
    action: str,
    payload: dict[str, Any],
    tenant: str | dict[str, Any] | TenantContext,
    destination_node: str = "gate",
    source_node: str = "client",
    reply_to: str = "client",
    priority: int = 2,
    timeout_ms: int = 30_000,
    classification: str = "internal",
    compliance_tags: tuple[str, ...] = (),
    retention_days: int = 90,
    expires_at: datetime | None = None,
    idempotency_key: str | None = None,
    trace_id: str | None = None,
    correlation_id: str | None = None,
    provenance: RoutingProvenance | None = None,
) -> TransportPacket:
    """Build a canonical root transport packet with initialized lineage and hashes."""
    packet_id = uuid4()
    normalized_tenant = ensure_tenant_context(tenant)
    normalized_action = action.strip().lower()
    normalized_source = source_node.strip().lower()
    normalized_destination = destination_node.strip().lower()
    normalized_reply_to = reply_to.strip().lower()

    header = TransportHeader(
        packet_id=packet_id,
        packet_type="request",
        action=normalized_action,
        priority=priority,
        created_at=utc_now(),
        expires_at=expires_at,
        timeout_ms=timeout_ms,
        schema_version="1.0",
        idempotency_key=idempotency_key,
        trace_id=trace_id or str(packet_id),
        correlation_id=correlation_id or str(packet_id),
        causation_id=None,
        retry_count=0,
        replay_mode=False,
        not_before=None,
    )

    address = TransportAddress(
        source_node=normalized_source,
        destination_node=normalized_destination,
        reply_to=normalized_reply_to,
    )

    governance = TransportGovernance(
        intent=normalized_action,
        compliance_tags=compliance_tags,
        retention_days=retention_days,
        redaction_applied=False,
        audit_required=False,
        data_subject_id=None,
    )

    packet = TransportPacket.model_construct(
        header=header,
        address=address,
        tenant=normalized_tenant,
        payload=dict(payload),
        security=TransportSecurity(
            payload_hash="0" * 64,
            transport_hash="0" * 64,
            signature=None,
            signature_algorithm=None,
            signing_key_id=None,
            classification=classification,
            encryption_status="plaintext",
            pii_fields=(),
        ),
        governance=governance,
        provenance=provenance or _default_provenance(source_node=normalized_source, action=normalized_action),
        delegation_chain=(),
        hop_trace=(),
        lineage=TransportLineage(
            parent_id=None,
            root_id=packet_id,
            generation=0,
        ),
        attachments=(),
    )
    return _finalize_transport_packet(packet)
# filename: src/constellation_node_sdk/transport/__init__.py
from .errors import (
    PacketSizeError,
    SchemaVersionError,
    TenantMutationError,
    TransportAuthenticationError,
    TransportAuthorizationError,
    TransportError,
    TransportExpiredError,
    TransportIntegrityError,
    TransportNotYetValidError,
    TransportValidationError,
)
from .hashing import canonical_json, compute_payload_hash, compute_transport_hash
from .models import (
    DelegationLink,
    TransportAddress,
    TransportAttachment,
    TransportGovernance,
    TransportHeader,
    TransportHop,
    TransportLineage,
    TransportSecurity,
    utc_now,
)
from .packet import TransportPacket, create_transport_packet
from .provenance import RoutingProvenance
from .tenant import TenantContext, assert_tenant_immutable, ensure_tenant_context

__all__ = [
    "DelegationLink",
    "PacketSizeError",
    "RoutingProvenance",
    "SchemaVersionError",
    "TenantContext",
    "TenantMutationError",
    "TransportAddress",
    "TransportAttachment",
    "TransportAuthenticationError",
    "TransportAuthorizationError",
    "TransportError",
    "TransportExpiredError",
    "TransportGovernance",
    "TransportHeader",
    "TransportHop",
    "TransportIntegrityError",
    "TransportLineage",
    "TransportNotYetValidError",
    "TransportPacket",
    "TransportSecurity",
    "TransportValidationError",
    "assert_tenant_immutable",
    "canonical_json",
    "compute_payload_hash",
    "compute_transport_hash",
    "create_transport_packet",
    "ensure_tenant_context",
    "utc_now",
]
Notes
These files intentionally establish:

immutable TransportPacket semantics

canonical payload and transport hashing

explicit routing provenance

lineage-preserving derive()

hop trace as append-only but excluded from transport hash so routing hops can accumulate without invalidating the stable signed transport core

🚀 Your Next Prompt

Generate the Phase 1 security layer files for constellation-node-sdk: complete runnable files for security/signing.py, security/verification.py, security/validation.py, and security/delegation.py, wired to these TransportPacket contracts and enforcing size, depth, clock-skew, signature, replay, delegation-scope, and tenant-immutability rules.

Reply Y to use this as your next prompt!


Explain in detail: hop trace as append-only but excluded from transport hash so routing hops can accumulate without invalidating the stable signed transport core

It means you are separating the packet into two layers of truth:

the signed transport core

the live routing journal

The signed transport core must stay stable enough to verify end-to-end intent and lineage. The hop trace must stay mutable enough to record what actually happened at each step.

If you hash and sign both together, you create a conflict:
every legitimate hop mutation changes the hash, which breaks the prior signature.

The problem you are avoiding
Take this flow:

client -> gate -> orchestrator -> gate -> worker
Suppose the client creates a packet and signs the whole thing, including hop_trace.

At creation time:

{
  "header": {...},
  "address": {...},
  "payload": {...},
  "lineage": {...},
  "hop_trace": []
}
Hash is computed over all of it.

Now Gate receives it and appends:

"hop_trace": [
  {"node": "gate", "direction": "ingress", ...}
]
The packet is now different bytes than what the client signed.
So one of two bad things happens:

either the signature now fails, or

Gate has to re-sign the whole packet, replacing the client’s original signed truth

Then the orchestrator adds another hop, and the same problem repeats.

So if hop_trace is inside the signed hash domain, the packet becomes re-sign-on-every-hop by necessity.

That has several costs:

destroys stable origin verification semantics

makes it harder to know what exactly the original sender attested to

forces every intermediary to become a signer of the full packet state

makes multi-hop auditing more complicated, not less

The core idea
So the cleaner model is:

Stable signed transport core
This contains the semantic identity of the packet:

header

address

tenant

payload

governance

provenance

delegation chain

lineage

attachments

payload hash

This is what the sender means to send.

Append-only hop trace
This contains operational history:

which node received it

which node dispatched it

timing

attempt count

error/status

target node for dispatch hops

This is not the message itself.
It is the travel log of the message.

So the transport hash says:

“These are the packet’s canonical semantics.”

And the hop trace says:

“Here is the observed path this packet took through the constellation.”

Why append-only matters
Append-only means:

hops can be added

existing hops cannot be mutated or deleted

history only grows forward

That gives you auditability without destabilizing the packet’s signed core.

For example:

At creation
transport_hash = H(core_fields)
hop_trace = []
signature = Sign(transport_hash)
At Gate ingress
transport_hash = same
hop_trace = [gate ingress]
signature = same
At Gate dispatch
transport_hash = same
hop_trace = [gate ingress, gate dispatch]
signature = same
So the packet’s semantic identity remains stable while the routing journal accumulates.

What the signature is now proving
With this model, the signature proves:

who created or last signed the canonical transport core

that payload, lineage, provenance, and governance were not tampered with

that action and routing intent were not altered silently

It does not prove that no additional hops happened after signing.

That is correct, because hop additions are expected and legitimate runtime events.

Why this is better for Gate-centric routing
Your architecture depends on repeated Gate re-entry:

client -> gate -> orchestrator -> gate -> worker
If every Gate pass mutates the signed domain, Gate must either:

invalidate the prior signature, or

fully re-sign the packet, or

create a new child packet every time just to add a hop

That becomes noisy and operationally heavy.

By excluding hop trace from the transport hash, Gate can record every pass without breaking transport integrity.

So you get:

stable core verification

rich operational history

no forced re-sign on pure observation events

Important nuance: lineage is different from hop trace
This distinction matters a lot.

Lineage
Lineage is part of the transport core because it defines causal identity:

root_id

parent_id

generation

If Node A derives a child packet to ask for more work, that is a semantically new packet.
It should get a new transport hash.

Hop trace
Hop trace is not causal identity.
It is runtime observation.

If Gate receives a packet and forwards it, that may be the same packet moving through the system.
Recording that movement should not redefine the packet’s semantic identity.

So:

derive child packet → new hash

append routing hop → same hash

That is the clean rule.

Mental model
Think of it like a shipping container.

Transport core
The sealed manifest attached to the container:

contents

sender

destination intent

tracking root

security classification

Hop trace
The stamps added at each checkpoint:

arrived at port

cleared customs

loaded on truck

delivered to depot

You do not rewrite the manifest every time someone stamps the outside.
You preserve the manifest and append handling history.

What this enables operationally
1. Origin integrity
You can always verify what the sender actually sent.

2. Cheap observability
Intermediaries can add routing history without recomputing the full trust envelope.

3. Better replay/debugging
You can inspect two dimensions separately:

what the packet was

where it went

4. Cleaner multi-hop orchestration
The orchestrator can derive new child packets when it truly creates new work, while Gate can append ingress/dispatch hops on those packets without destabilizing their signed core.

The tradeoff
This design does mean:

hop trace is not protected by the same exact hash as the transport core.

So if you do nothing else, a malicious intermediary could theoretically alter hop entries without changing transport_hash.

That is the main tradeoff.

How to handle that tradeoff correctly
There are a few good ways.

Option A: trust hop trace as operational telemetry
Good enough for many internal systems if Gate is the authority.

Option B: sign each hop entry independently
Each node can append a hop with its own hop-level signature.

Then the hop trace becomes an append-only signed journal.

Option C: maintain a separate hop-chain hash
Each hop includes something like:

hop_chain_hash_n = H(hop_chain_hash_n-1 + canonical(hop_n))
That gives tamper-evident ordering without putting hop trace inside the transport core hash.

This is often the best design.

Best practice for your constellation
For your architecture, I would recommend this split:

Transport hash covers
header

address

tenant

payload

governance

provenance

delegation chain

lineage

attachments

payload hash

Hop trace is excluded from transport hash, but each hop contains
node

direction

timestamp

status

optional target node

optional previous_hop_hash

optional hop_signature

That gives you:

stable packet identity

append-only routing history

tamper evidence for the operational journal

When hop trace should change the hash
Only if you define hop addition as creating a new semantic packet version.

I would not do that for your system, because Gate passes are frequent and observational.

I would reserve new transport hashes for:

child packet derivation

payload mutation

governance mutation

destination/provenance mutation

delegation changes

lineage changes

Not for:

ingress recording

dispatch recording

timing/status recording

The short architectural rule
The transport hash protects what the packet means.
The hop trace records where the packet went.

Those are related, but they should not be the same layer.

Concrete example
Original packet
{
  "header": {"packet_id": "p1", "action": "enrich"},
  "address": {"source_node": "orchestrator", "destination_node": "gate"},
  "payload": {"entity_id": "42"},
  "lineage": {"root_id": "r1", "parent_id": "p0", "generation": 2},
  "hop_trace": []
}
Compute:

payload_hash   = H(payload)
transport_hash = H(header + address + tenant + payload + governance + provenance + delegation_chain + lineage + attachments + payload_hash)
signature      = Sign(transport_hash)
After Gate ingress
"hop_trace": [
  {
    "node": "gate",
    "direction": "ingress",
    "status": "validated",
    "timestamp": "..."
  }
]
Now:

payload_hash unchanged

transport_hash unchanged

signature still valid

After Gate dispatch
"hop_trace": [
  {"node": "gate", "direction": "ingress", ...},
  {"node": "gate", "direction": "dispatch", "target_node": "enrich", ...}
]
Still:

payload_hash unchanged

transport_hash unchanged

signature still valid

That is the behavior you want.

Bottom line
Excluding hop trace from the transport hash is a deliberate design choice so that:

the packet’s semantic core remains stable and signable

routing history can grow naturally at runtime

Gate can record every ingress/dispatch event

orchestration does not force full re-signing for observational changes

The clean follow-on refinement is:

make hop trace append-only and independently tamper-evident, rather than folding it into the transport hash.

🚀 Your Next Prompt

Refine the TransportPacket design by specifying a tamper-evident hop trace model with exact fields for previous_hop_hash, hop_hash, and optional hop_signature, plus validation rules for how Gate and nodes append hops without changing transport_hash.

Reply Y to use this as your next prompt!


Y

Strategic reasoning:

The prior split is correct: keep transport_hash stable over the semantic packet core, and make hop_trace mutable. The missing piece is tamper evidence for the mutable journal. The best design is a second integrity plane: a hash chain over hops plus optional per-hop signatures. That preserves stable packet verification while making route history append-only and tamper-evident. This is the simplest high-leverage refinement because it upgrades audit quality without re-coupling routing telemetry to the transport core hash.

Tamper-Evident Hop Trace Model
Design objective
Keep these two properties true at the same time:

transport_hash stays stable unless the semantic packet changes

hop_trace is append-only and tamper-evident as nodes add routing history

Architectural rule
transport_hash protects packet meaning

hop_trace protects packet journey

hop tamper evidence is enforced by a hop chain, not by folding hops back into transport_hash

1. Refined model
Transport core hash domain
transport_hash continues to cover:

header

address

tenant

payload

governance

provenance

delegation_chain

lineage

attachments

payload_hash

It does not include hop_trace.

Hop integrity domain
Each hop independently commits to:

stable packet identity via transport_hash

the prior hop via previous_hop_hash

its own operational data via hop_hash

optionally, node authenticity via hop_signature

That gives you an append-only, chained audit log.

2. Exact hop model
class TransportHop(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    hop_id: UUID = Field(default_factory=uuid4)
    packet_id: UUID
    node: str
    action: str
    direction: Literal["ingress", "dispatch", "execution", "response"]
    status: Literal["received", "validated", "processing", "delegated", "completed", "failed"]
    timestamp: datetime = Field(default_factory=utc_now)

    attempt: int | None = Field(default=None, ge=1)
    target_node: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    queue_ms: int | None = Field(default=None, ge=0)
    network_ms: int | None = Field(default=None, ge=0)
    error_code: str | None = None
    error_message: str | None = None

    previous_hop_hash: str | None = None
    hop_hash: str
    hop_signature: str | None = None
    hop_signature_algorithm: str | None = None
    hop_signing_key_id: str | None = None
Required fields by meaning
Identity / binding
hop_id

packet_id

node

action

Routing semantics
direction

status

target_node

Timing / diagnostics
timestamp

attempt

duration_ms

queue_ms

network_ms

error_code

error_message

Tamper evidence
previous_hop_hash

hop_hash

hop_signature

hop_signature_algorithm

hop_signing_key_id

3. Canonical hop hash algorithm
Hash input
Each hop hash must include:

the packet’s transport_hash

the previous hop hash

the hop’s own canonical fields

That binds the hop to both:

the semantic packet

the exact ordered chain before it

Canonical hash payload
def compute_hop_hash(
    *,
    transport_hash: str,
    hop: TransportHop,
) -> str:
    payload = {
        "transport_hash": transport_hash,
        "hop_id": str(hop.hop_id),
        "packet_id": str(hop.packet_id),
        "node": hop.node,
        "action": hop.action,
        "direction": hop.direction,
        "status": hop.status,
        "timestamp": hop.timestamp,
        "attempt": hop.attempt,
        "target_node": hop.target_node,
        "duration_ms": hop.duration_ms,
        "queue_ms": hop.queue_ms,
        "network_ms": hop.network_ms,
        "error_code": hop.error_code,
        "error_message": hop.error_message,
        "previous_hop_hash": hop.previous_hop_hash,
    }
    return sha256(canonical_json(payload)).hexdigest()
Why include transport_hash
This prevents a valid hop chain from being copied onto a different packet.
A hop is cryptographically bound to one transport core.

4. Hop append rules
Rule A: append-only
A node may only:

add a new hop to the end of hop_trace

A node may never:

delete a prior hop

reorder hops

mutate any existing hop fields

Rule B: chain continuity
For hop n:

previous_hop_hash must equal hop_trace[n-1].hop_hash

first hop must have previous_hop_hash = None

Rule C: hash correctness
For every hop:

recompute hop_hash

recomputed value must equal stored hop_hash

Rule D: packet binding
For every hop:

packet_id must equal packet.header.packet_id

hop hash must be computed using the packet’s current transport_hash

Rule E: optional hop signature correctness
If hop_signature is present:

hop_signature_algorithm is required

hop_signing_key_id is required

signature verifies over hop_hash

5. Signature model
Transport signature
The packet-level signature signs transport_hash.

This proves:

sender authenticity over semantic packet content

stable integrity of payload, lineage, governance, provenance, etc.

Hop signature
A hop-level signature signs hop_hash.

This proves:

a specific node attested to this routing event

the hop existed in this exact ordered position

the hop was bound to this exact transport core

Recommended practice
client-originated packets: transport signature required in prod

Gate-added hops: hop signature strongly recommended

worker/orchestrator-added execution hops: hop signature recommended

internal dev mode: signatures may be relaxed, chain hashing remains

6. Validation rules
Packet validation
validate_transport_packet(packet) checks:

payload hash

transport hash

transport signature if required

size/depth/clock/replay/delegation rules

Hop trace validation
Add a second validator:

def validate_hop_trace(
    packet: TransportPacket,
    *,
    verify_hop_signatures: bool = False,
    hop_key_resolver: Callable[[str | None], str | bytes | None] | None = None,
) -> None: ...
Validation steps
Step 1: packet binding
For each hop:

hop.packet_id == packet.header.packet_id

Step 2: chain order
For index 0:

previous_hop_hash is None

For index i > 0:

previous_hop_hash == hop_trace[i - 1].hop_hash

Step 3: hash integrity
For each hop:

recompute hop_hash from canonical hop payload + packet transport_hash

require equality

Step 4: signature integrity
If verify_hop_signatures=True:

verify each present hop_signature against hop_hash

Step 5: semantic consistency
Examples:

direction="dispatch" should usually require target_node

status="failed" may require error_code or error_message

timestamps must be non-decreasing

7. How Gate appends hops
Gate ingress hop
When Gate receives a valid packet:

hop = make_ingress_hop(
    packet=packet,
    node="gate",
    action=packet.header.action,
    status="validated",
    previous_hop_hash=last_hop_hash(packet),
)
packet = packet.with_hop(hop)
This does not change:

payload_hash

transport_hash

packet transport signature

It does change:

hop_trace

Gate dispatch hop
When Gate resolves and dispatches:

hop = make_dispatch_hop(
    packet=packet,
    node="gate",
    action=packet.header.action,
    status="delegated",
    target_node=resolved.node_name,
    previous_hop_hash=last_hop_hash(packet),
)
packet = packet.with_hop(hop)
Again:

transport core unchanged

hop chain extended

8. How nodes append hops
Worker execution hop
Worker receives packet, validates transport core, validates hop chain, then appends:

hop = make_execution_hop(
    packet=packet,
    node="score",
    action=packet.header.action,
    status="processing",
    previous_hop_hash=last_hop_hash(packet),
)
packet = packet.with_hop(hop)
Worker response hop
Before returning:

hop = make_response_hop(
    packet=response_packet,
    node="score",
    action=response_packet.header.action,
    status="completed",
    previous_hop_hash=last_hop_hash(response_packet),
)
response_packet = response_packet.with_hop(hop)
9. Important distinction: same packet vs derived child packet
Same packet: append hop only
Use when recording movement or execution state.

Effects:

transport_hash unchanged

hop_trace extended

transport signature remains valid

hop chain grows

Derived child packet: new transport hash
Use when semantic work changes:

new packet id

new parent id

generation increment

changed payload, address, governance, provenance, delegation, etc.

Effects:

new transport_hash

new transport signature required

new hop chain starts empty or starts with child’s first hop

Clean rule
routing observation → append hop

causal semantic mutation → derive child packet

10. Recommended helper API
Helpers
def last_hop_hash(packet: TransportPacket) -> str | None: ...

def compute_hop_hash(*, transport_hash: str, hop: TransportHop) -> str: ...

def sign_hop(
    hop: TransportHop,
    *,
    key: bytes | str,
    key_id: str,
    algorithm: str,
) -> TransportHop: ...

def validate_hop_trace(
    packet: TransportPacket,
    *,
    verify_hop_signatures: bool = False,
    hop_key_resolver: Callable[[str | None], str | bytes | None] | None = None,
) -> None: ...
Hop constructors
def make_ingress_hop(...) -> TransportHop: ...
def make_dispatch_hop(...) -> TransportHop: ...
def make_execution_hop(...) -> TransportHop: ...
def make_response_hop(...) -> TransportHop: ...
Each constructor should:

build the hop payload without hop_hash

compute hop_hash

optionally sign it

return immutable finalized hop

11. Example chain
Assume packet has:

transport_hash = TH1
Hop 1: Gate ingress
previous_hop_hash = None
hop_hash = H(TH1 + hop1_fields + None)
Hop 2: Gate dispatch
previous_hop_hash = hop1_hash
hop_hash = H(TH1 + hop2_fields + hop1_hash)
Hop 3: Worker execution
previous_hop_hash = hop2_hash
hop_hash = H(TH1 + hop3_fields + hop2_hash)
Now if someone edits hop 2:

hop 2 hash no longer validates

hop 3 previous pointer no longer matches

chain breaks visibly

That is the tamper-evident property you want.

12. Failure modes detected by this model
Mutation of old hop
Detected because stored hop_hash no longer matches recomputed value.

Reordering hops
Detected because previous_hop_hash chain no longer lines up.

Deleting a middle hop
Detected because the next hop’s previous_hop_hash becomes orphaned.

Copying hop trace to another packet
Detected because hop hashes are bound to the original transport_hash.

Forging a signed hop
Detected if hop signatures are verified and key resolution is configured.

13. Best-practice policy for your constellation
Minimum required
hop hash chain required for all hops

hop trace validation required at Gate ingress and worker ingress

Strongly recommended
Gate signs all ingress and dispatch hops

workers sign execution and response hops

Optional in dev
hop signatures disabled

hop hash chain still enabled

That gives you low-friction local development without sacrificing structure.

14. Final rule set
Packet core
immutable semantic content

protected by transport_hash

optionally authenticated by transport signature

Hop journal
append-only operational log

excluded from transport_hash

protected by per-hop hash chain

optionally authenticated by hop signatures

Causal transitions
semantic change → derive child packet

observational event → append hop

That is the clean transport model.

15. Recommended exact validation contract
def validate_transport_packet(packet: TransportPacket, ...) -> None:
    # validates semantic core only
    ...

def validate_hop_trace(
    packet: TransportPacket,
    *,
    verify_hop_signatures: bool = False,
    hop_key_resolver: Callable[[str | None], str | bytes | None] | None = None,
    require_monotonic_timestamps: bool = True,
) -> None:
    # validates append-only operational journal
    ...
This separation is important. It keeps the two integrity planes explicit and debuggable.

🚀 Your Next Prompt

Generate the Phase 1 hop-integrity files for constellation-node-sdk: complete runnable files for transport/hop_trace.py and updates to transport/models.py and transport/packet.py that add previous_hop_hash, hop_hash, optional hop_signature, constructors for ingress/dispatch/execution/response hops, and a validate_hop_trace() function consistent with the stable transport_hash design.

Reply Y to use this as your next prompt!


Y


Thought for 35s
Strategic reasoning:

This is the right next move. The stable transport_hash design only becomes operationally safe once the mutable hop_trace gets its own integrity plane. The minimal complete implementation is: extend TransportHop, make TransportPacket.with_hop() preserve the transport signature, and add a hop-chain utility module that computes, signs, appends, and validates hops without changing the packet’s semantic hash. That is the smallest change that closes the design gap cleanly.

Below are the complete updated files.

# filename: src/constellation_node_sdk/transport/models.py
from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_ALLOWED_PACKET_TYPES = {
    "request",
    "response",
    "event",
    "command",
    "delegation",
    "failure",
    "replay_request",
    "replay_response",
    "compensation",
}
_ALLOWED_CLASSIFICATIONS = {"public", "internal", "confidential", "restricted"}
_ALLOWED_ENCRYPTION = {"plaintext", "encrypted", "envelope_only"}
_ALLOWED_SIGNATURE_ALGORITHMS = {"hmac-sha256", "ed25519"}
_ALLOWED_HOP_DIRECTIONS = {"ingress", "dispatch", "execution", "response"}
_ALLOWED_HOP_STATUSES = {"received", "validated", "processing", "delegated", "completed", "failed"}
_ACTION_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def utc_now() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(UTC)


def ensure_utc(value: datetime | None) -> datetime | None:
    """Normalize a datetime to UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def normalize_optional_string(value: str | None) -> str | None:
    """Normalize an optional string, forbidding blank-but-present values."""
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        raise ValueError("optional string fields must not be blank")
    return normalized


def validate_sha256_hex(value: str, *, field_name: str) -> str:
    """Validate that a value is a 64-character lowercase SHA-256 hex digest."""
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(ch not in "0123456789abcdef" for ch in normalized):
        raise ValueError(f"{field_name} must be a 64-char lowercase sha256 hex digest")
    return normalized


class TransportHeader(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    packet_id: UUID = Field(default_factory=uuid4)
    packet_type: str
    action: str
    priority: int = 2
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime | None = None
    timeout_ms: int = Field(default=30_000, ge=1)

    schema_version: str = "1.0"
    idempotency_key: str | None = None
    trace_id: str | None = None
    correlation_id: str | None = None
    causation_id: UUID | None = None
    retry_count: int = Field(default=0, ge=0)
    replay_mode: bool = False
    not_before: datetime | None = None

    @field_validator("packet_type")
    @classmethod
    def validate_packet_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_PACKET_TYPES:
            msg = f"packet_type must be one of {sorted(_ALLOWED_PACKET_TYPES)}"
            raise ValueError(msg)
        return normalized

    @field_validator("action")
    @classmethod
    def validate_action(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _ACTION_RE.match(normalized):
            raise ValueError("action must be lowercase alphanumeric + dash, max 64 chars")
        return normalized

    @field_validator("priority", mode="before")
    @classmethod
    def coerce_priority(cls, value: Any) -> int:
        if isinstance(value, str):
            rendered = value.strip().upper()
            if rendered in {"P0", "P1", "P2", "P3"}:
                return int(rendered[-1])
            return int(rendered)
        return int(value)

    @field_validator("created_at", "expires_at", "not_before")
    @classmethod
    def normalize_datetimes(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value)

    @field_validator("idempotency_key", "trace_id", "correlation_id", "schema_version")
    @classmethod
    def validate_optional_strings(cls, value: str | None) -> str | None:
        return normalize_optional_string(value)

    @model_validator(mode="after")
    def validate_header(self) -> "TransportHeader":
        if not 0 <= self.priority <= 3:
            raise ValueError("priority must be between 0 and 3")
        if self.expires_at is not None and self.expires_at <= self.created_at:
            raise ValueError("expires_at must be later than created_at")
        if self.not_before is not None and self.not_before < self.created_at:
            raise ValueError("not_before must not be earlier than created_at")
        return self


class TransportAddress(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_node: str
    destination_node: str
    reply_to: str

    @field_validator("source_node", "destination_node", "reply_to")
    @classmethod
    def validate_node_name(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("address fields must not be empty")
        return normalized


class TransportSecurity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    payload_hash: str
    transport_hash: str
    signature: str | None = None
    signature_algorithm: str | None = None
    signing_key_id: str | None = None
    classification: str = "internal"
    encryption_status: str = "plaintext"
    pii_fields: tuple[str, ...] = ()

    @field_validator("payload_hash", "transport_hash")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return validate_sha256_hex(value, field_name="hash field")

    @field_validator("signature", "signing_key_id")
    @classmethod
    def validate_optional_strings(cls, value: str | None) -> str | None:
        return normalize_optional_string(value)

    @field_validator("signature_algorithm")
    @classmethod
    def validate_signature_algorithm(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_SIGNATURE_ALGORITHMS:
            msg = f"signature_algorithm must be one of {sorted(_ALLOWED_SIGNATURE_ALGORITHMS)}"
            raise ValueError(msg)
        return normalized

    @field_validator("classification")
    @classmethod
    def validate_classification(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_CLASSIFICATIONS:
            msg = f"classification must be one of {sorted(_ALLOWED_CLASSIFICATIONS)}"
            raise ValueError(msg)
        return normalized

    @field_validator("encryption_status")
    @classmethod
    def validate_encryption_status(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_ENCRYPTION:
            msg = f"encryption_status must be one of {sorted(_ALLOWED_ENCRYPTION)}"
            raise ValueError(msg)
        return normalized

    @field_validator("pii_fields", mode="before")
    @classmethod
    def coerce_pii_fields(cls, value: Any) -> Any:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value

    @field_validator("pii_fields")
    @classmethod
    def validate_pii_fields(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(path.strip() for path in value if path.strip())
        if len(set(normalized)) != len(normalized):
            raise ValueError("pii_fields must not contain duplicates")
        return normalized

    @model_validator(mode="after")
    def validate_signature_state(self) -> "TransportSecurity":
        if self.signature is not None and self.signature_algorithm is None:
            raise ValueError("signature_algorithm is required when signature is present")
        if self.signature_algorithm is not None and self.signature is None:
            raise ValueError("signature is required when signature_algorithm is present")
        return self


class TransportGovernance(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    intent: str
    compliance_tags: tuple[str, ...] = ()
    retention_days: int = Field(default=90, ge=0)
    redaction_applied: bool = False
    audit_required: bool = False
    data_subject_id: str | None = None

    @field_validator("intent")
    @classmethod
    def validate_intent(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("intent must not be empty")
        return normalized

    @field_validator("compliance_tags", mode="before")
    @classmethod
    def coerce_compliance_tags(cls, value: Any) -> Any:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value

    @field_validator("compliance_tags")
    @classmethod
    def validate_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(tag.strip().upper() for tag in value if tag.strip())
        if len(set(normalized)) != len(normalized):
            raise ValueError("compliance_tags must not contain duplicates")
        return normalized

    @field_validator("data_subject_id")
    @classmethod
    def validate_data_subject_id(cls, value: str | None) -> str | None:
        return normalize_optional_string(value)


class TransportLineage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    parent_id: UUID | None = None
    root_id: UUID
    generation: int = Field(default=0, ge=0)


class TransportAttachment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    attachment_id: UUID = Field(default_factory=uuid4)
    media_type: str
    uri: str
    content_hash: str
    encrypted: bool = True
    size_bytes: int = Field(ge=0)

    @field_validator("media_type", "uri")
    @classmethod
    def validate_required_strings(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("attachment fields must not be empty")
        return normalized

    @field_validator("content_hash")
    @classmethod
    def validate_content_hash(cls, value: str) -> str:
        return validate_sha256_hex(value, field_name="attachment content_hash")


class TransportHop(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    hop_id: UUID = Field(default_factory=uuid4)
    packet_id: UUID
    node: str
    action: str
    direction: str
    status: str
    timestamp: datetime = Field(default_factory=utc_now)

    attempt: int | None = Field(default=None, ge=1)
    target_node: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    queue_ms: int | None = Field(default=None, ge=0)
    network_ms: int | None = Field(default=None, ge=0)
    error_code: str | None = None
    error_message: str | None = None

    previous_hop_hash: str | None = None
    hop_hash: str
    hop_signature: str | None = None
    hop_signature_algorithm: str | None = None
    hop_signing_key_id: str | None = None

    @field_validator("node", "action")
    @classmethod
    def validate_required_strings(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("hop fields must not be empty")
        return normalized

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_HOP_DIRECTIONS:
            msg = f"direction must be one of {sorted(_ALLOWED_HOP_DIRECTIONS)}"
            raise ValueError(msg)
        return normalized

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_HOP_STATUSES:
            msg = f"status must be one of {sorted(_ALLOWED_HOP_STATUSES)}"
            raise ValueError(msg)
        return normalized

    @field_validator("timestamp")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        normalized = ensure_utc(value)
        if normalized is None:
            raise ValueError("timestamp must not be null")
        return normalized

    @field_validator("target_node", "error_code", "error_message", "hop_signature", "hop_signing_key_id")
    @classmethod
    def validate_optional_strings(cls, value: str | None) -> str | None:
        return normalize_optional_string(value)

    @field_validator("previous_hop_hash", "hop_hash")
    @classmethod
    def validate_hop_hashes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_sha256_hex(value, field_name="hop hash")

    @field_validator("hop_signature_algorithm")
    @classmethod
    def validate_hop_signature_algorithm(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_SIGNATURE_ALGORITHMS:
            msg = f"hop_signature_algorithm must be one of {sorted(_ALLOWED_SIGNATURE_ALGORITHMS)}"
            raise ValueError(msg)
        return normalized

    @model_validator(mode="after")
    def validate_hop(self) -> "TransportHop":
        if self.direction == "dispatch" and self.target_node is None:
            raise ValueError("dispatch hops require target_node")
        if self.hop_signature is not None:
            if self.hop_signature_algorithm is None:
                raise ValueError("hop_signature_algorithm is required when hop_signature is present")
            if self.hop_signing_key_id is None:
                raise ValueError("hop_signing_key_id is required when hop_signature is present")
        if self.hop_signature_algorithm is not None and self.hop_signature is None:
            raise ValueError("hop_signature is required when hop_signature_algorithm is present")
        if self.hop_signing_key_id is not None and self.hop_signature is None:
            raise ValueError("hop_signature is required when hop_signing_key_id is present")
        if self.status == "failed" and self.error_code is None and self.error_message is None:
            raise ValueError("failed hops require error_code or error_message")
        return self


class DelegationLink(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    delegator: str
    delegatee: str
    scope: tuple[str, ...]
    granted_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime | None = None
    constraints: dict[str, Any] | None = None
    proof: str | None = None

    @field_validator("delegator", "delegatee")
    @classmethod
    def validate_nodes(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("delegation node fields must not be empty")
        return normalized

    @field_validator("scope", mode="before")
    @classmethod
    def coerce_scope(cls, value: Any) -> Any:
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value

    @field_validator("scope")
    @classmethod
    def validate_scope(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip().lower() for item in value if item.strip())
        if not normalized:
            raise ValueError("scope must not be empty")
        if len(set(normalized)) != len(normalized):
            raise ValueError("scope must not contain duplicates")
        return normalized

    @field_validator("granted_at", "expires_at")
    @classmethod
    def normalize_datetimes(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value)

    @field_validator("proof")
    @classmethod
    def validate_proof(cls, value: str | None) -> str | None:
        return normalize_optional_string(value)

    @model_validator(mode="after")
    def validate_expiry(self) -> "DelegationLink":
        if self.expires_at is not None and self.expires_at <= self.granted_at:
            raise ValueError("expires_at must be later than granted_at")
        return self
# filename: src/constellation_node_sdk/transport/packet.py
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from .errors import TransportIntegrityError
from .hashing import compute_payload_hash, compute_transport_hash
from .models import (
    DelegationLink,
    TransportAddress,
    TransportAttachment,
    TransportGovernance,
    TransportHeader,
    TransportHop,
    TransportLineage,
    TransportSecurity,
    utc_now,
)
from .provenance import RoutingProvenance
from .tenant import TenantContext, assert_tenant_immutable, ensure_tenant_context


class TransportPacket(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    header: TransportHeader
    address: TransportAddress
    tenant: TenantContext
    payload: dict[str, Any]
    security: TransportSecurity
    governance: TransportGovernance
    provenance: RoutingProvenance
    delegation_chain: tuple[DelegationLink, ...] = ()
    hop_trace: tuple[TransportHop, ...] = ()
    lineage: TransportLineage
    attachments: tuple[TransportAttachment, ...] = ()

    @field_validator("payload")
    @classmethod
    def validate_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise TypeError("payload must be a dict")
        return value

    @model_validator(mode="after")
    def validate_integrity(self) -> "TransportPacket":
        expected_payload_hash = compute_payload_hash(self.payload)
        if self.security.payload_hash != expected_payload_hash:
            raise TransportIntegrityError("payload_hash does not match payload")

        expected_transport_hash = compute_transport_hash(self)
        if self.security.transport_hash != expected_transport_hash:
            raise TransportIntegrityError("transport_hash does not match packet")

        return self

    def model_dump_json_dict(self) -> dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return self.model_dump(mode="json", exclude_none=True)

    def with_hop(self, hop: TransportHop) -> "TransportPacket":
        """
        Append a hop without mutating the signed transport core.

        hop_trace is intentionally excluded from transport_hash, so a hop append
        must preserve payload_hash, transport_hash, and any existing transport
        signature.
        """
        if hop.packet_id != self.header.packet_id:
            raise ValueError("hop.packet_id must match packet.header.packet_id")

        appended = self.model_copy(update={"hop_trace": self.hop_trace + (hop,)})
        return TransportPacket(
            header=appended.header,
            address=appended.address,
            tenant=appended.tenant,
            payload=appended.payload,
            security=appended.security,
            governance=appended.governance,
            provenance=appended.provenance,
            delegation_chain=tuple(appended.delegation_chain),
            hop_trace=tuple(appended.hop_trace),
            lineage=appended.lineage,
            attachments=tuple(appended.attachments),
        )

    def derive(
        self,
        *,
        packet_type: str | None = None,
        action: str | None = None,
        source_node: str | None = None,
        destination_node: str | None = None,
        reply_to: str | None = None,
        payload: dict[str, Any] | None = None,
        provenance: RoutingProvenance | None = None,
        hop: TransportHop | None = None,
        delegation_link: DelegationLink | None = None,
        governance: TransportGovernance | None = None,
        priority: int | None = None,
        expires_at: datetime | None = None,
        timeout_ms: int | None = None,
        not_before: datetime | None = None,
        replay_mode: bool | None = None,
    ) -> "TransportPacket":
        """Create an immutable child packet with correct lineage and refreshed hashes."""
        new_header = TransportHeader(
            packet_id=uuid4(),
            packet_type=packet_type or self.header.packet_type,
            action=action or self.header.action,
            priority=self.header.priority if priority is None else priority,
            created_at=utc_now(),
            expires_at=self.header.expires_at if expires_at is None else expires_at,
            timeout_ms=self.header.timeout_ms if timeout_ms is None else timeout_ms,
            schema_version=self.header.schema_version,
            idempotency_key=self.header.idempotency_key,
            trace_id=self.header.trace_id,
            correlation_id=self.header.correlation_id,
            causation_id=self.header.packet_id,
            retry_count=0,
            replay_mode=self.header.replay_mode if replay_mode is None else replay_mode,
            not_before=self.header.not_before if not_before is None else not_before,
        )

        new_address = TransportAddress(
            source_node=(source_node or self.address.source_node).strip().lower(),
            destination_node=(destination_node or self.address.destination_node).strip().lower(),
            reply_to=(reply_to or self.address.reply_to).strip().lower(),
        )

        new_payload = dict(self.payload if payload is None else payload)
        new_governance = governance or self.governance
        new_provenance = provenance or self.provenance
        new_delegation_chain = self.delegation_chain + ((delegation_link,) if delegation_link is not None else ())
        new_hop_trace = self.hop_trace + ((hop,) if hop is not None else ())
        new_lineage = TransportLineage(
            parent_id=self.header.packet_id,
            root_id=self.lineage.root_id,
            generation=self.lineage.generation + 1,
        )

        provisional = TransportPacket.model_construct(
            header=new_header,
            address=new_address,
            tenant=self.tenant,
            payload=new_payload,
            security=TransportSecurity(
                payload_hash="0" * 64,
                transport_hash="0" * 64,
                signature=None,
                signature_algorithm=None,
                signing_key_id=None,
                classification=self.security.classification,
                encryption_status=self.security.encryption_status,
                pii_fields=self.security.pii_fields,
            ),
            governance=new_governance,
            provenance=new_provenance,
            delegation_chain=new_delegation_chain,
            hop_trace=new_hop_trace,
            lineage=new_lineage,
            attachments=self.attachments,
        )
        child = _finalize_transport_packet(provisional, preserve_signature=False)
        assert_tenant_immutable(self.tenant, child.tenant)
        return child


def _default_provenance(*, source_node: str, action: str) -> RoutingProvenance:
    source = source_node.strip().lower()
    origin_kind = "client" if source == "client" else "gate" if source == "gate" else "node"
    return RoutingProvenance(
        origin_kind=origin_kind,
        requested_action=action.strip().lower(),
        resolved_by_gate=False,
        original_source_node=None if origin_kind == "client" else source,
    )


def _finalize_transport_packet(packet: TransportPacket, *, preserve_signature: bool) -> TransportPacket:
    payload_hash = compute_payload_hash(packet.payload)
    provisional = packet.model_copy(
        update={
            "security": packet.security.model_copy(
                update={
                    "payload_hash": payload_hash,
                    "transport_hash": "0" * 64,
                    "signature": packet.security.signature if preserve_signature else None,
                    "signature_algorithm": packet.security.signature_algorithm if preserve_signature else None,
                    "signing_key_id": packet.security.signing_key_id if preserve_signature else None,
                }
            )
        }
    )
    transport_hash = compute_transport_hash(provisional)
    signature_still_valid = (
        preserve_signature
        and packet.security.payload_hash == payload_hash
        and packet.security.transport_hash == transport_hash
    )

    finalized = provisional.model_copy(
        update={
            "security": provisional.security.model_copy(
                update={
                    "transport_hash": transport_hash,
                    "signature": packet.security.signature if signature_still_valid else None,
                    "signature_algorithm": packet.security.signature_algorithm if signature_still_valid else None,
                    "signing_key_id": packet.security.signing_key_id if signature_still_valid else None,
                }
            )
        }
    )
    return TransportPacket(
        header=finalized.header,
        address=finalized.address,
        tenant=finalized.tenant,
        payload=finalized.payload,
        security=finalized.security,
        governance=finalized.governance,
        provenance=finalized.provenance,
        delegation_chain=tuple(finalized.delegation_chain),
        hop_trace=tuple(finalized.hop_trace),
        lineage=finalized.lineage,
        attachments=tuple(finalized.attachments),
    )


def create_transport_packet(
    *,
    action: str,
    payload: dict[str, Any],
    tenant: str | dict[str, Any] | TenantContext,
    destination_node: str = "gate",
    source_node: str = "client",
    reply_to: str = "client",
    priority: int = 2,
    timeout_ms: int = 30_000,
    classification: str = "internal",
    compliance_tags: tuple[str, ...] = (),
    retention_days: int = 90,
    expires_at: datetime | None = None,
    idempotency_key: str | None = None,
    trace_id: str | None = None,
    correlation_id: str | None = None,
    provenance: RoutingProvenance | None = None,
) -> TransportPacket:
    """Build a canonical root transport packet with initialized lineage and hashes."""
    packet_id = uuid4()
    normalized_tenant = ensure_tenant_context(tenant)
    normalized_action = action.strip().lower()
    normalized_source = source_node.strip().lower()
    normalized_destination = destination_node.strip().lower()
    normalized_reply_to = reply_to.strip().lower()

    header = TransportHeader(
        packet_id=packet_id,
        packet_type="request",
        action=normalized_action,
        priority=priority,
        created_at=utc_now(),
        expires_at=expires_at,
        timeout_ms=timeout_ms,
        schema_version="1.0",
        idempotency_key=idempotency_key,
        trace_id=trace_id or str(packet_id),
        correlation_id=correlation_id or str(packet_id),
        causation_id=None,
        retry_count=0,
        replay_mode=False,
        not_before=None,
    )

    address = TransportAddress(
        source_node=normalized_source,
        destination_node=normalized_destination,
        reply_to=normalized_reply_to,
    )

    governance = TransportGovernance(
        intent=normalized_action,
        compliance_tags=compliance_tags,
        retention_days=retention_days,
        redaction_applied=False,
        audit_required=False,
        data_subject_id=None,
    )

    packet = TransportPacket.model_construct(
        header=header,
        address=address,
        tenant=normalized_tenant,
        payload=dict(payload),
        security=TransportSecurity(
            payload_hash="0" * 64,
            transport_hash="0" * 64,
            signature=None,
            signature_algorithm=None,
            signing_key_id=None,
            classification=classification,
            encryption_status="plaintext",
            pii_fields=(),
        ),
        governance=governance,
        provenance=provenance or _default_provenance(source_node=normalized_source, action=normalized_action),
        delegation_chain=(),
        hop_trace=(),
        lineage=TransportLineage(
            parent_id=None,
            root_id=packet_id,
            generation=0,
        ),
        attachments=(),
    )
    return _finalize_transport_packet(packet, preserve_signature=False)
# filename: src/constellation_node_sdk/transport/hop_trace.py
from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any
from uuid import uuid4

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key, load_pem_public_key

from .errors import TransportAuthenticationError, TransportIntegrityError, TransportValidationError
from .hashing import canonical_json
from .models import TransportHop, ensure_utc, utc_now
from .packet import TransportPacket


def _coerce_bytes(value: str | bytes) -> bytes:
    if isinstance(value, bytes):
        return value
    normalized = value.strip()
    if normalized.startswith("-----BEGIN"):
        return normalized.encode("utf-8")
    try:
        return base64.b64decode(normalized, validate=True)
    except Exception:
        return normalized.encode("utf-8")


def _resolve_key(
    key_resolver: Callable[[str | None], str | bytes | None] | Mapping[str, str | bytes] | str | bytes | None,
    key_id: str | None,
) -> bytes | None:
    if key_resolver is None:
        return None
    if isinstance(key_resolver, (bytes, str)):
        return _coerce_bytes(key_resolver)
    if callable(key_resolver):
        value = key_resolver(key_id)
    else:
        if key_id is None:
            return None
        value = key_resolver.get(key_id)
    if value is None:
        return None
    return _coerce_bytes(value)


def _load_ed25519_private_key(raw: bytes) -> Ed25519PrivateKey:
    if raw.startswith(b"-----BEGIN"):
        loaded = load_pem_private_key(raw, password=None)
        if not isinstance(loaded, Ed25519PrivateKey):
            raise TransportAuthenticationError("PEM private key is not Ed25519")
        return loaded
    if len(raw) == 32:
        return Ed25519PrivateKey.from_private_bytes(raw)
    raise TransportAuthenticationError("unsupported ed25519 private key format")


def _load_ed25519_public_key(raw: bytes) -> Ed25519PublicKey:
    if raw.startswith(b"-----BEGIN"):
        loaded = load_pem_public_key(raw)
        if not isinstance(loaded, Ed25519PublicKey):
            raise TransportAuthenticationError("PEM public key is not Ed25519")
        return loaded
    if len(raw) == 32:
        return Ed25519PublicKey.from_public_bytes(raw)
    raise TransportAuthenticationError("unsupported ed25519 public key format")


def last_hop_hash(packet: TransportPacket) -> str | None:
    """Return the last hop hash in a packet, if any."""
    if not packet.hop_trace:
        return None
    return packet.hop_trace[-1].hop_hash


def compute_hop_hash(*, transport_hash: str, hop: TransportHop) -> str:
    """
    Compute the hop hash bound to both the packet transport core and the
    previous hop in the chain.
    """
    payload = {
        "transport_hash": transport_hash,
        "hop_id": str(hop.hop_id),
        "packet_id": str(hop.packet_id),
        "node": hop.node,
        "action": hop.action,
        "direction": hop.direction,
        "status": hop.status,
        "timestamp": hop.timestamp,
        "attempt": hop.attempt,
        "target_node": hop.target_node,
        "duration_ms": hop.duration_ms,
        "queue_ms": hop.queue_ms,
        "network_ms": hop.network_ms,
        "error_code": hop.error_code,
        "error_message": hop.error_message,
        "previous_hop_hash": hop.previous_hop_hash,
    }
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def sign_hop(
    hop: TransportHop,
    *,
    key: bytes | str,
    key_id: str,
    algorithm: str,
) -> TransportHop:
    """Sign a hop hash using HMAC-SHA256 or Ed25519."""
    normalized_algorithm = algorithm.strip().lower()
    raw_key = _coerce_bytes(key)

    if normalized_algorithm == "hmac-sha256":
        signature = hmac.new(raw_key, hop.hop_hash.encode("utf-8"), hashlib.sha256).hexdigest()
    elif normalized_algorithm == "ed25519":
        private_key = _load_ed25519_private_key(raw_key)
        signature = private_key.sign(hop.hop_hash.encode("utf-8")).hex()
    else:
        raise TransportAuthenticationError(f"unsupported hop signature algorithm: {normalized_algorithm}")

    return hop.model_copy(
        update={
            "hop_signature": signature,
            "hop_signature_algorithm": normalized_algorithm,
            "hop_signing_key_id": key_id.strip(),
        }
    )


def verify_hop_signature(
    hop: TransportHop,
    *,
    key_resolver: Callable[[str | None], str | bytes | None] | Mapping[str, str | bytes] | str | bytes | None,
) -> bool:
    """Verify an optional hop signature."""
    if hop.hop_signature is None or hop.hop_signature_algorithm is None:
        return False

    key = _resolve_key(key_resolver, hop.hop_signing_key_id)
    if key is None:
        raise TransportAuthenticationError("no verifying key available for hop signature verification")

    if hop.hop_signature_algorithm == "hmac-sha256":
        expected = hmac.new(key, hop.hop_hash.encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(hop.hop_signature, expected)

    if hop.hop_signature_algorithm == "ed25519":
        public_key = _load_ed25519_public_key(key)
        try:
            public_key.verify(bytes.fromhex(hop.hop_signature), hop.hop_hash.encode("utf-8"))
            return True
        except (ValueError, InvalidSignature) as exc:
            raise TransportAuthenticationError("invalid ed25519 hop signature") from exc

    raise TransportAuthenticationError(f"unsupported hop signature algorithm: {hop.hop_signature_algorithm}")


def _finalize_hop(
    *,
    packet: TransportPacket,
    node: str,
    action: str,
    direction: str,
    status: str,
    attempt: int | None = None,
    target_node: str | None = None,
    duration_ms: int | None = None,
    queue_ms: int | None = None,
    network_ms: int | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    timestamp: datetime | None = None,
    key: bytes | str | None = None,
    key_id: str | None = None,
    algorithm: str | None = None,
) -> TransportHop:
    provisional = TransportHop(
        hop_id=uuid4(),
        packet_id=packet.header.packet_id,
        node=node.strip().lower(),
        action=action.strip().lower(),
        direction=direction.strip().lower(),
        status=status.strip().lower(),
        timestamp=ensure_utc(timestamp) or utc_now(),
        attempt=attempt,
        target_node=None if target_node is None else target_node.strip().lower(),
        duration_ms=duration_ms,
        queue_ms=queue_ms,
        network_ms=network_ms,
        error_code=error_code,
        error_message=error_message,
        previous_hop_hash=last_hop_hash(packet),
        hop_hash="0" * 64,
        hop_signature=None,
        hop_signature_algorithm=None,
        hop_signing_key_id=None,
    )
    hop_hash = compute_hop_hash(transport_hash=packet.security.transport_hash, hop=provisional)
    finalized = provisional.model_copy(update={"hop_hash": hop_hash})

    if key is not None:
        if key_id is None or algorithm is None:
            raise TransportValidationError("key_id and algorithm are required when signing a hop")
        finalized = sign_hop(finalized, key=key, key_id=key_id, algorithm=algorithm)

    return TransportHop.model_validate(finalized)


def make_ingress_hop(
    *,
    packet: TransportPacket,
    node: str,
    action: str,
    status: str = "validated",
    attempt: int | None = None,
    queue_ms: int | None = None,
    key: bytes | str | None = None,
    key_id: str | None = None,
    algorithm: str | None = None,
) -> TransportHop:
    """Create a finalized ingress hop."""
    return _finalize_hop(
        packet=packet,
        node=node,
        action=action,
        direction="ingress",
        status=status,
        attempt=attempt,
        queue_ms=queue_ms,
        key=key,
        key_id=key_id,
        algorithm=algorithm,
    )


def make_dispatch_hop(
    *,
    packet: TransportPacket,
    node: str,
    action: str,
    target_node: str,
    status: str = "delegated",
    attempt: int | None = None,
    network_ms: int | None = None,
    key: bytes | str | None = None,
    key_id: str | None = None,
    algorithm: str | None = None,
) -> TransportHop:
    """Create a finalized dispatch hop."""
    return _finalize_hop(
        packet=packet,
        node=node,
        action=action,
        direction="dispatch",
        status=status,
        attempt=attempt,
        target_node=target_node,
        network_ms=network_ms,
        key=key,
        key_id=key_id,
        algorithm=algorithm,
    )


def make_execution_hop(
    *,
    packet: TransportPacket,
    node: str,
    action: str,
    status: str = "processing",
    attempt: int | None = None,
    duration_ms: int | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    key: bytes | str | None = None,
    key_id: str | None = None,
    algorithm: str | None = None,
) -> TransportHop:
    """Create a finalized execution hop."""
    return _finalize_hop(
        packet=packet,
        node=node,
        action=action,
        direction="execution",
        status=status,
        attempt=attempt,
        duration_ms=duration_ms,
        error_code=error_code,
        error_message=error_message,
        key=key,
        key_id=key_id,
        algorithm=algorithm,
    )


def make_response_hop(
    *,
    packet: TransportPacket,
    node: str,
    action: str,
    status: str = "completed",
    attempt: int | None = None,
    duration_ms: int | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    key: bytes | str | None = None,
    key_id: str | None = None,
    algorithm: str | None = None,
) -> TransportHop:
    """Create a finalized response hop."""
    return _finalize_hop(
        packet=packet,
        node=node,
        action=action,
        direction="response",
        status=status,
        attempt=attempt,
        duration_ms=duration_ms,
        error_code=error_code,
        error_message=error_message,
        key=key,
        key_id=key_id,
        algorithm=algorithm,
    )


def validate_hop_trace(
    packet: TransportPacket,
    *,
    verify_hop_signatures: bool = False,
    hop_key_resolver: Callable[[str | None], str | bytes | None] | Mapping[str, str | bytes] | str | bytes | None = None,
    require_monotonic_timestamps: bool = True,
) -> None:
    """
    Validate the append-only, tamper-evident hop chain for a packet.

    The hop chain is bound to packet.security.transport_hash but intentionally
    excluded from that hash so hops can accumulate without invalidating the
    transport signature.
    """
    previous_hash: str | None = None
    previous_timestamp: datetime | None = None

    for index, hop in enumerate(packet.hop_trace):
        if hop.packet_id != packet.header.packet_id:
            raise TransportValidationError("hop packet_id does not match packet header packet_id")

        if index == 0:
            if hop.previous_hop_hash is not None:
                raise TransportIntegrityError("first hop must set previous_hop_hash to null")
        elif hop.previous_hop_hash != previous_hash:
            raise TransportIntegrityError("hop chain continuity violation detected")

        recomputed = compute_hop_hash(transport_hash=packet.security.transport_hash, hop=hop)
        if hop.hop_hash != recomputed:
            raise TransportIntegrityError("hop_hash does not match recomputed hop hash")

        if require_monotonic_timestamps and previous_timestamp is not None and hop.timestamp < previous_timestamp:
            raise TransportValidationError("hop timestamps must be non-decreasing")

        if verify_hop_signatures and hop.hop_signature is not None:
            if not verify_hop_signature(hop, key_resolver=hop_key_resolver):
                raise TransportAuthenticationError("invalid hop signature")

        previous_hash = hop.hop_hash
        previous_timestamp = hop.timestamp
🚀 Your Next Prompt

Generate the Phase 1 security layer files for constellation-node-sdk: complete runnable files for security/signing.py, security/verification.py, security/validation.py, and security/delegation.py, wired to the updated TransportPacket and hop-integrity model, including transport signature verification, replay/delegation checks, and optional hop-signature verification in packet validation.

Reply Y to use this as your next prompt!


Y


Thought for 25s
Strategic reasoning:

The next leverage point is to make the transport contract actually enforceable. That means the packet model and hop-chain model now need a real security layer: signing, verification, full validation, and delegation proof generation. These four files are the minimum complete set to make TransportPacket trustworthy across Gate and nodes.

# filename: src/constellation_node_sdk/security/signing.py
from __future__ import annotations

import base64
import hashlib
import hmac

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from constellation_node_sdk.transport.hashing import compute_payload_hash, compute_transport_hash
from constellation_node_sdk.transport.models import TransportSecurity
from constellation_node_sdk.transport.packet import TransportPacket

from .verification import TransportAuthenticationError


def _coerce_bytes(value: str | bytes) -> bytes:
    if isinstance(value, bytes):
        return value
    normalized = value.strip()
    if normalized.startswith("-----BEGIN"):
        return normalized.encode("utf-8")
    try:
        return base64.b64decode(normalized, validate=True)
    except Exception:
        return normalized.encode("utf-8")


def _load_ed25519_private_key(raw: bytes) -> Ed25519PrivateKey:
    if raw.startswith(b"-----BEGIN"):
        loaded = load_pem_private_key(raw, password=None)
        if not isinstance(loaded, Ed25519PrivateKey):
            raise TransportAuthenticationError("PEM private key is not Ed25519")
        return loaded
    if len(raw) == 32:
        return Ed25519PrivateKey.from_private_bytes(raw)
    raise TransportAuthenticationError("unsupported ed25519 private key format")


def recompute_transport_core(packet: TransportPacket) -> TransportPacket:
    """
    Recompute payload_hash and transport_hash while preserving hop_trace.

    hop_trace is intentionally excluded from transport_hash.
    Any existing packet signature is cleared and must be re-applied by the caller.
    """
    payload_hash = compute_payload_hash(packet.payload)

    provisional = packet.model_copy(
        update={
            "security": packet.security.model_copy(
                update={
                    "payload_hash": payload_hash,
                    "transport_hash": "0" * 64,
                    "signature": None,
                    "signature_algorithm": None,
                    "signing_key_id": None,
                }
            )
        }
    )

    transport_hash = compute_transport_hash(provisional)
    finalized = provisional.model_copy(
        update={
            "security": provisional.security.model_copy(
                update={
                    "transport_hash": transport_hash,
                }
            )
        }
    )

    return TransportPacket.model_validate(finalized)


def sign_transport_packet(
    packet: TransportPacket,
    *,
    key: bytes | str,
    key_id: str,
    algorithm: str,
) -> TransportPacket:
    """
    Sign a transport packet over its stable transport_hash.

    The packet's hop_trace is preserved, but is not included in the signature domain.
    """
    normalized_algorithm = algorithm.strip().lower()
    raw_key = _coerce_bytes(key)
    normalized = recompute_transport_core(packet)

    if normalized_algorithm == "hmac-sha256":
        signature = hmac.new(
            raw_key,
            normalized.security.transport_hash.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
    elif normalized_algorithm == "ed25519":
        private_key = _load_ed25519_private_key(raw_key)
        signature = private_key.sign(normalized.security.transport_hash.encode("utf-8")).hex()
    else:
        raise TransportAuthenticationError(f"unsupported signature algorithm: {normalized_algorithm}")

    signed = normalized.model_copy(
        update={
            "security": TransportSecurity(
                payload_hash=normalized.security.payload_hash,
                transport_hash=normalized.security.transport_hash,
                signature=signature,
                signature_algorithm=normalized_algorithm,
                signing_key_id=key_id.strip(),
                classification=normalized.security.classification,
                encryption_status=normalized.security.encryption_status,
                pii_fields=normalized.security.pii_fields,
            )
        }
    )
    return TransportPacket.model_validate(signed)
# filename: src/constellation_node_sdk/security/verification.py
from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Callable, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from constellation_node_sdk.transport.errors import TransportAuthenticationError
from constellation_node_sdk.transport.packet import TransportPacket


def _coerce_bytes(value: str | bytes) -> bytes:
    if isinstance(value, bytes):
        return value
    normalized = value.strip()
    if normalized.startswith("-----BEGIN"):
        return normalized.encode("utf-8")
    try:
        return base64.b64decode(normalized, validate=True)
    except Exception:
        return normalized.encode("utf-8")


def _resolve_key(
    key_resolver: Callable[[str | None], str | bytes | None] | Mapping[str, str | bytes] | str | bytes | None,
    key_id: str | None,
) -> bytes | None:
    if key_resolver is None:
        return None
    if isinstance(key_resolver, (bytes, str)):
        return _coerce_bytes(key_resolver)
    if callable(key_resolver):
        value = key_resolver(key_id)
    else:
        if key_id is None:
            return None
        value = key_resolver.get(key_id)
    if value is None:
        return None
    return _coerce_bytes(value)


def _load_ed25519_public_key(raw: bytes) -> Ed25519PublicKey:
    if raw.startswith(b"-----BEGIN"):
        loaded = load_pem_public_key(raw)
        if not isinstance(loaded, Ed25519PublicKey):
            raise TransportAuthenticationError("PEM public key is not Ed25519")
        return loaded
    if len(raw) == 32:
        return Ed25519PublicKey.from_public_bytes(raw)
    raise TransportAuthenticationError("unsupported ed25519 public key format")


def verify_transport_packet_signature(
    packet: TransportPacket,
    *,
    key_resolver: Callable[[str | None], str | bytes | None] | Mapping[str, str | bytes] | str | bytes | None,
) -> bool:
    """
    Verify the packet signature against packet.security.transport_hash.

    Returns False if the packet is unsigned.
    Raises TransportAuthenticationError for key resolution or verification failures.
    """
    if packet.security.signature is None or packet.security.signature_algorithm is None:
        return False

    key = _resolve_key(key_resolver, packet.security.signing_key_id)
    if key is None:
        raise TransportAuthenticationError("no verifying key available for transport signature verification")

    if packet.security.signature_algorithm == "hmac-sha256":
        expected = hmac.new(
            key,
            packet.security.transport_hash.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(packet.security.signature, expected)

    if packet.security.signature_algorithm == "ed25519":
        public_key = _load_ed25519_public_key(key)
        try:
            public_key.verify(
                bytes.fromhex(packet.security.signature),
                packet.security.transport_hash.encode("utf-8"),
            )
            return True
        except (ValueError, InvalidSignature) as exc:
            raise TransportAuthenticationError("invalid ed25519 transport signature") from exc

    raise TransportAuthenticationError(f"unsupported signature algorithm: {packet.security.signature_algorithm}")
# filename: src/constellation_node_sdk/security/delegation.py
from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import UTC, datetime
from typing import Any

from constellation_node_sdk.transport.hashing import canonical_json
from constellation_node_sdk.transport.packet import TransportPacket


def _coerce_bytes(value: str | bytes) -> bytes:
    if isinstance(value, bytes):
        return value
    normalized = value.strip()
    try:
        return base64.b64decode(normalized, validate=True)
    except Exception:
        return normalized.encode("utf-8")


def compute_delegation_proof(
    *,
    packet: TransportPacket,
    delegator: str,
    delegatee: str,
    scope: tuple[str, ...],
    granted_at: datetime,
    key: bytes | str,
    expires_at: datetime | None = None,
    constraints: dict[str, Any] | None = None,
) -> str:
    """
    Compute an HMAC proof for a delegation grant.

    Delegation proofs are bound to:
    - packet_id
    - transport_hash
    - delegator/delegatee
    - scope
    - grant time
    - optional expiry/constraints
    """
    raw_key = _coerce_bytes(key)
    normalized_scope = tuple(item.strip().lower() for item in scope if item.strip())
    message = {
        "packet_id": str(packet.header.packet_id),
        "transport_hash": packet.security.transport_hash,
        "delegator": delegator.strip().lower(),
        "delegatee": delegatee.strip().lower(),
        "scope": list(normalized_scope),
        "granted_at": granted_at.astimezone(UTC).isoformat(),
        "expires_at": expires_at.astimezone(UTC).isoformat() if expires_at else None,
        "constraints": constraints or {},
    }
    return hmac.new(raw_key, canonical_json(message), hashlib.sha256).hexdigest()
# filename: src/constellation_node_sdk/security/validation.py
from __future__ import annotations

import ipaddress
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from constellation_node_sdk.security.verification import (
    TransportAuthenticationError,
    verify_transport_packet_signature,
)
from constellation_node_sdk.transport.errors import (
    PacketSizeError,
    SchemaVersionError,
    TenantMutationError,
    TransportAuthorizationError,
    TransportExpiredError,
    TransportIntegrityError,
    TransportNotYetValidError,
    TransportValidationError,
)
from constellation_node_sdk.transport.hop_trace import validate_hop_trace
from constellation_node_sdk.transport.packet import TransportPacket
from constellation_node_sdk.transport.tenant import assert_tenant_immutable


def transport_packet_size_bytes(packet: TransportPacket) -> int:
    """Return the canonical JSON size of a packet in bytes."""
    return len(
        json.dumps(
            packet.model_dump_json_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    )


def validate_derived_transport_packet(parent: TransportPacket, child: TransportPacket) -> None:
    """Validate parent/child lineage and tenant immutability for a derived packet."""
    try:
        assert_tenant_immutable(parent.tenant, child.tenant)
    except TenantMutationError:
        raise
    except Exception as exc:  # defensive normalization
        raise TenantMutationError(str(exc)) from exc

    if child.lineage.parent_id != parent.header.packet_id:
        raise TransportValidationError("derived packet parent_id mismatch")
    if child.lineage.root_id != parent.lineage.root_id:
        raise TransportValidationError("derived packet root_id mismatch")
    if child.lineage.generation != parent.lineage.generation + 1:
        raise TransportValidationError("derived packet generation must increment by 1")


def validate_transport_packet(
    packet: TransportPacket,
    *,
    key_resolver: Callable[[str | None], str | bytes | None] | Mapping[str, str | bytes] | str | bytes | None = None,
    require_signature: bool = False,
    max_packet_bytes: int = 262_144,
    max_hop_depth: int = 64,
    max_delegation_depth: int = 8,
    max_attachments: int = 32,
    max_attachment_size_bytes: int = 10_485_760,
    allowed_attachment_schemes: tuple[str, ...] = (),
    allow_private_attachment_hosts: bool = False,
    allowed_clock_skew_seconds: int = 30,
    local_node: str | None = None,
    allowed_actions: tuple[str, ...] | None = None,
    allowed_packet_types: tuple[str, ...] | None = None,
    required_idempotency_actions: tuple[str, ...] | None = None,
    replay_enabled: bool = True,
    now: datetime | None = None,
    dev_mode: bool = False,
    verify_hop_signatures: bool = False,
    hop_key_resolver: Callable[[str | None], str | bytes | None] | Mapping[str, str | bytes] | str | bytes | None = None,
    require_monotonic_hop_timestamps: bool = True,
) -> None:
    """
    Validate a transport packet's semantic core, delegation semantics, and optional hop integrity.
    """
    current_time = (now or datetime.now(UTC)).astimezone(UTC)

    if packet.header.schema_version != "1.0":
        raise SchemaVersionError(f"unsupported schema_version: {packet.header.schema_version}")

    if allowed_packet_types is not None and packet.header.packet_type not in set(allowed_packet_types):
        raise TransportAuthorizationError(f"packet_type not allowed: {packet.header.packet_type}")

    if allowed_actions is not None and packet.header.action not in set(allowed_actions):
        raise TransportAuthorizationError(f"action not allowed: {packet.header.action}")

    if local_node is not None and packet.address.destination_node != local_node.strip().lower():
        raise TransportAuthorizationError("packet destination does not match this node")

    if packet.header.created_at > current_time + timedelta(seconds=allowed_clock_skew_seconds):
        raise TransportValidationError("packet created_at exceeds allowed clock skew")

    if transport_packet_size_bytes(packet) > max_packet_bytes:
        raise PacketSizeError("packet exceeds maximum allowed size")

    if len(packet.hop_trace) > max_hop_depth:
        raise TransportValidationError("hop trace exceeds maximum depth")

    if len(packet.delegation_chain) > max_delegation_depth:
        raise TransportValidationError("delegation chain exceeds maximum depth")

    if len(packet.attachments) > max_attachments:
        raise TransportValidationError("attachment count exceeds maximum")

    for attachment in packet.attachments:
        if attachment.size_bytes > max_attachment_size_bytes:
            raise TransportValidationError("attachment exceeds maximum allowed size")
        _validate_attachment_uri(
            attachment.uri,
            allowed_schemes=allowed_attachment_schemes,
            allow_private_hosts=allow_private_attachment_hosts,
        )

    # Model validation already checks payload_hash and transport_hash.
    # This block exists as an explicit semantic assertion boundary.
    if not packet.security.payload_hash or not packet.security.transport_hash:
        raise TransportIntegrityError("packet hashes are missing")

    if packet.header.not_before is not None and current_time < packet.header.not_before:
        raise TransportNotYetValidError("packet not valid yet")

    if packet.header.expires_at is not None and current_time > packet.header.expires_at:
        raise TransportExpiredError("packet TTL exceeded")

    if packet.header.packet_type == "replay_request":
        if not packet.header.replay_mode:
            raise TransportValidationError("replay_request packets must set replay_mode=true")
        if not replay_enabled:
            raise TransportAuthorizationError("replay is disabled on this service")

    if packet.header.replay_mode and packet.header.packet_type != "replay_request":
        raise TransportValidationError("replay_mode is only permitted for replay_request packets")

    if required_idempotency_actions and packet.header.action in set(required_idempotency_actions):
        if not packet.header.idempotency_key:
            raise TransportValidationError("idempotency_key required for this action")

    if "GDPR" in packet.governance.compliance_tags and not packet.governance.data_subject_id:
        raise TransportValidationError("GDPR packets require data_subject_id")

    if packet.security.classification == "restricted" and packet.governance.audit_required is not True:
        raise TransportValidationError("restricted packets must set audit_required=true")

    _validate_delegation_chain(packet, now=current_time)

    if packet.security.signature is None:
        if (require_signature or packet.security.classification == "restricted") and not dev_mode:
            raise TransportAuthenticationError("signature required but not present")
    else:
        if not (dev_mode and key_resolver is None):
            if not verify_transport_packet_signature(packet, key_resolver=key_resolver):
                raise TransportAuthenticationError("invalid transport signature")

    validate_hop_trace(
        packet,
        verify_hop_signatures=verify_hop_signatures,
        hop_key_resolver=hop_key_resolver,
        require_monotonic_timestamps=require_monotonic_hop_timestamps,
    )


def _validate_delegation_chain(packet: TransportPacket, *, now: datetime) -> None:
    previous_scope: set[str] | None = None

    for index, link in enumerate(packet.delegation_chain):
        current_scope = set(link.scope)

        if previous_scope is not None and not current_scope.issubset(previous_scope):
            raise TransportAuthorizationError("delegation scope escalation detected")

        if link.expires_at is not None and now > link.expires_at.astimezone(UTC):
            raise TransportAuthorizationError("delegation link expired")

        if index == len(packet.delegation_chain) - 1 and packet.header.packet_type == "delegation":
            if packet.header.action not in current_scope:
                raise TransportAuthorizationError("delegated packet action not permitted by last delegation scope")
            if packet.address.destination_node != link.delegatee:
                raise TransportAuthorizationError("delegated packet destination does not match last delegation target")

        previous_scope = current_scope


def _validate_attachment_uri(uri: str, *, allowed_schemes: tuple[str, ...], allow_private_hosts: bool) -> None:
    parsed = urlparse(uri)
    scheme = parsed.scheme.lower()

    if not scheme:
        raise TransportValidationError("attachment uri must include a scheme")
    if allowed_schemes and scheme not in set(allowed_schemes):
        raise TransportValidationError(f"attachment scheme not allowed: {scheme}")
    if scheme in {"file", "ftp"}:
        raise TransportValidationError(f"attachment scheme not allowed: {scheme}")

    hostname = parsed.hostname
    if hostname is None:
        if scheme in {"https", "http"}:
            raise TransportValidationError("http(s) attachment uri must include a host")
        return

    normalized_host = hostname.lower()
    if normalized_host in {"localhost", "metadata.google.internal"}:
        raise TransportValidationError("attachment host not allowed")

    try:
        host_ip = ipaddress.ip_address(normalized_host)
    except ValueError:
        return

    if not allow_private_hosts and (host_ip.is_private or host_ip.is_loopback or host_ip.is_link_local):
        raise TransportValidationError("private attachment hosts are not allowed")
These files give you:

transport-core rehash + signing

transport signature verification

delegation proof generation

packet validation for size, depth, clock skew, replay, idempotency, governance, delegation scope

optional hop-signature verification layered into packet validation

🚀 Your Next Prompt

Generate the Phase 1 Gate client layer for constellation-node-sdk: complete runnable files for gate/config.py, gate/policy.py, gate/client.py, and gate/registration.py, enforcing Gate-only destination rules, canonical TransportPacket request/response handling, and node self-registration from spec.yaml.

Reply Y to use this as your next prompt!


Y

Strategic reasoning:

This is the right next layer. Once TransportPacket and security validation exist, the highest-leverage follow-up is the Gate boundary client that all nodes must use. That client is where you hard-enforce the architectural law: node-originated packets go only to Gate, never peer URLs. These four files make the SDK operational for worker and orchestrator nodes without reintroducing legacy transport drift.

# filename: src/constellation_node_sdk/gate/config.py
from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class GateClientConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    gate_url: str
    local_node: str
    timeout_seconds: float = Field(default=30.0, gt=0.0)
    require_signature: bool = False
    signing_key: str | bytes | None = None
    signing_key_id: str | None = None
    signing_algorithm: str | None = None
    verify_response_signatures: bool = False
    verifying_keys: dict[str, str] = Field(default_factory=dict)
    verify_hop_signatures: bool = False
    allowed_gate_destination: str = "gate"

    @field_validator("gate_url")
    @classmethod
    def validate_gate_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if not normalized:
            raise ValueError("gate_url must not be empty")
        if not (normalized.startswith("http://") or normalized.startswith("https://")):
            raise ValueError("gate_url must start with http:// or https://")
        return normalized

    @field_validator("local_node", "allowed_gate_destination")
    @classmethod
    def validate_node_fields(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("node fields must not be empty")
        return normalized

    @field_validator("signing_key_id", "signing_algorithm")
    @classmethod
    def validate_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("optional string fields must not be blank")
        return normalized

    @field_validator("verifying_keys")
    @classmethod
    def validate_verifying_keys(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for key_id, key_value in value.items():
            normalized_key = key_id.strip()
            normalized_value = key_value.strip()
            if not normalized_key or not normalized_value:
                raise ValueError("verifying_keys must not contain blank keys or values")
            normalized[normalized_key] = normalized_value
        return normalized

    def resolve_verifying_key(self, key_id: str | None) -> str | bytes | None:
        if key_id is None:
            return None
        if key_id in self.verifying_keys:
            return self.verifying_keys[key_id]
        if self.signing_key_id is not None and key_id == self.signing_key_id and self.signing_key is not None:
            return self.signing_key
        return None


class GateRegistrationConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    gate_url: str
    admin_token: str | None = None
    spec_path: str = "engine/spec.yaml"
    registration_enabled: bool = True
    retries: int = Field(default=3, ge=1)
    overwrite: bool = True

    @field_validator("gate_url")
    @classmethod
    def validate_gate_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if not normalized:
            raise ValueError("gate_url must not be empty")
        if not (normalized.startswith("http://") or normalized.startswith("https://")):
            raise ValueError("gate_url must start with http:// or https://")
        return normalized

    @field_validator("admin_token", "spec_path")
    @classmethod
    def validate_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("optional string fields must not be blank")
        return normalized


def get_gate_client_config_from_env() -> GateClientConfig:
    gate_url = os.getenv("GATE_URL", "").strip()
    if not gate_url:
        raise ValueError("GATE_URL is required")

    local_node = os.getenv("L9_NODE_NAME", "unknown-node").strip().lower() or "unknown-node"
    signing_key = os.getenv("L9_SIGNING_KEY") or os.getenv("L9_SIGNING_SECRET")
    signing_key_id = os.getenv("L9_SIGNING_KEY_ID")
    signing_algorithm = os.getenv("L9_SIGNING_ALGORITHM")
    verify_response_signatures = _env_bool("L9_REQUIRE_SIGNATURE", False)

    return GateClientConfig(
        gate_url=gate_url,
        local_node=local_node,
        timeout_seconds=float(os.getenv("GATE_CLIENT_TIMEOUT_SECONDS", "30.0")),
        require_signature=_env_bool("L9_REQUIRE_SIGNATURE", False),
        signing_key=signing_key,
        signing_key_id=signing_key_id,
        signing_algorithm=signing_algorithm,
        verify_response_signatures=verify_response_signatures,
        verifying_keys={},
        verify_hop_signatures=_env_bool("L9_VERIFY_HOP_SIGNATURES", False),
        allowed_gate_destination=os.getenv("GATE_ALLOWED_DESTINATION", "gate"),
    )


def get_gate_registration_config_from_env() -> GateRegistrationConfig:
    gate_url = os.getenv("GATE_URL", "").strip()
    if not gate_url:
        raise ValueError("GATE_URL is required")

    return GateRegistrationConfig(
        gate_url=gate_url,
        admin_token=os.getenv("GATE_ADMIN_TOKEN") or None,
        spec_path=os.getenv("GATE_NODE_SPEC_PATH", "engine/spec.yaml"),
        registration_enabled=_env_bool("GATE_REGISTRATION_ENABLED", True),
        retries=int(os.getenv("GATE_REGISTER_RETRIES", "3")),
        overwrite=_env_bool("GATE_REGISTER_OVERWRITE", True),
    )
# filename: src/constellation_node_sdk/gate/policy.py
from __future__ import annotations

from constellation_node_sdk.transport.packet import TransportPacket


def assert_node_origin_packet(packet: TransportPacket) -> None:
    """
    Require that a packet sent through the Gate client is node-originated.

    External clients should speak to Gate directly without going through the node SDK.
    """
    source = packet.address.source_node.strip().lower()
    if source in {"", "client"}:
        raise ValueError("Gate client only accepts node-originated packets with non-client source_node")

    provenance_origin = packet.provenance.origin_kind.strip().lower()
    if provenance_origin != "node":
        raise ValueError("Gate client requires packet.provenance.origin_kind == 'node'")


def assert_gate_only_destination(packet: TransportPacket, *, gate_node_name: str = "gate") -> None:
    """
    Enforce the architectural rule that node-originated packets target Gate only.
    """
    normalized_gate = gate_node_name.strip().lower()
    destination = packet.address.destination_node.strip().lower()

    if destination != normalized_gate:
        raise ValueError(
            f"node-originated packets must target {normalized_gate!r}, got {destination!r}"
        )

    requested_action = packet.provenance.requested_action.strip().lower()
    if requested_action != packet.header.action:
        raise ValueError("packet.provenance.requested_action must match packet.header.action")


def assert_local_node_identity(packet: TransportPacket, *, local_node: str) -> None:
    """
    Ensure the packet source matches the local runtime node identity.
    """
    normalized_local = local_node.strip().lower()
    if packet.address.source_node != normalized_local:
        raise ValueError(
            f"packet source_node {packet.address.source_node!r} does not match local node {normalized_local!r}"
        )

    original_source = packet.provenance.original_source_node
    if original_source is not None and original_source != normalized_local:
        raise ValueError(
            "packet.provenance.original_source_node must match local node for node-originated packets"
        )


def validate_outbound_gate_packet(
    packet: TransportPacket,
    *,
    local_node: str,
    gate_node_name: str = "gate",
) -> None:
    """
    Apply the full outbound routing policy for the Gate client.
    """
    assert_node_origin_packet(packet)
    assert_local_node_identity(packet, local_node=local_node)
    assert_gate_only_destination(packet, gate_node_name=gate_node_name)
# filename: src/constellation_node_sdk/gate/client.py
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import httpx

from constellation_node_sdk.security.signing import sign_transport_packet
from constellation_node_sdk.security.validation import validate_transport_packet
from constellation_node_sdk.transport.packet import TransportPacket

from .config import GateClientConfig
from .policy import validate_outbound_gate_packet


class GateClient:
    """
    Canonical Gate-only transport client for nodes.

    This client is the only allowed outbound inter-node transport surface.
    It never accepts an arbitrary peer URL.
    """

    def __init__(self, config: GateClientConfig) -> None:
        self._config = config

    @property
    def gate_url(self) -> str:
        return self._config.gate_url

    def _transport_key_resolver(self) -> Callable[[str | None], str | bytes | None] | Mapping[str, str | bytes] | None:
        if not self._config.verifying_keys and self._config.signing_key is None:
            return None
        return self._config.resolve_verifying_key

    def _maybe_sign(self, packet: TransportPacket) -> TransportPacket:
        if self._config.signing_key is None:
            return packet
        if self._config.signing_key_id is None or self._config.signing_algorithm is None:
            raise ValueError("signing_key_id and signing_algorithm are required when signing_key is configured")
        return sign_transport_packet(
            packet,
            key=self._config.signing_key,
            key_id=self._config.signing_key_id,
            algorithm=self._config.signing_algorithm,
        )

    def _validate_outbound(self, packet: TransportPacket) -> None:
        validate_outbound_gate_packet(
            packet,
            local_node=self._config.local_node,
            gate_node_name=self._config.allowed_gate_destination,
        )
        validate_transport_packet(
            packet,
            key_resolver=self._transport_key_resolver(),
            require_signature=self._config.require_signature,
            dev_mode=not self._config.require_signature,
            verify_hop_signatures=self._config.verify_hop_signatures,
        )

    def _validate_inbound_response(self, packet: TransportPacket) -> None:
        validate_transport_packet(
            packet,
            key_resolver=self._transport_key_resolver(),
            require_signature=self._config.verify_response_signatures,
            dev_mode=not self._config.verify_response_signatures,
            verify_hop_signatures=self._config.verify_hop_signatures,
        )

    async def send_to_gate(self, packet: TransportPacket) -> TransportPacket:
        """
        Send a canonical TransportPacket to Gate and decode a canonical TransportPacket response.
        """
        self._validate_outbound(packet)
        signed_packet = self._maybe_sign(packet)

        async with httpx.AsyncClient(timeout=self._config.timeout_seconds) as client:
            response = await client.post(
                f"{self._config.gate_url}/v1/execute",
                json=signed_packet.model_dump_json_dict(),
                headers={"Content-Type": "application/json"},
            )

        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("Gate response body must be a JSON object")

        response_packet = TransportPacket.model_validate(body)
        self._validate_inbound_response(response_packet)
        return response_packet

    async def health(self) -> dict[str, Any]:
        """
        Query Gate health endpoint.
        """
        async with httpx.AsyncClient(timeout=self._config.timeout_seconds) as client:
            response = await client.get(f"{self._config.gate_url}/v1/health")
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("Gate health response must be a JSON object")
        return body
# filename: src/constellation_node_sdk/gate/registration.py
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
import yaml

from .config import GateRegistrationConfig, get_gate_registration_config_from_env

_DEFAULT_RETRY_BASE_SECONDS = 1.0


def load_node_spec(spec_path: str) -> dict[str, Any]:
    """
    Load node spec.yaml and require a top-level mapping.
    """
    path = Path(spec_path)
    if not path.exists():
        raise FileNotFoundError(f"node spec not found: {path.resolve()}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"node spec must be a YAML mapping: {path}")
    return raw


def build_registration_payload(spec: dict[str, Any]) -> dict[str, Any]:
    """
    Convert spec.yaml into Gate admin registration payload.

    Required:
    - node.id
    - node.actions
    """
    node = spec.get("node", {})
    if not isinstance(node, dict) or not node:
        raise ValueError("spec.yaml missing required node block")

    node_id = str(node.get("id", "")).strip().lower()
    if not node_id:
        raise ValueError("spec.yaml node.id is required")

    actions_raw = node.get("actions", [])
    if not isinstance(actions_raw, list) or not actions_raw:
        raise ValueError(f"spec.yaml node.actions must not be empty (node: {node_id})")

    actions = [str(action).strip().lower() for action in actions_raw if str(action).strip()]
    if not actions:
        raise ValueError(f"spec.yaml node.actions must contain at least one non-blank action (node: {node_id})")

    internal_url = str(node.get("internal_url", f"http://{node_id}:8000")).strip().rstrip("/")
    if not internal_url:
        raise ValueError("spec.yaml node.internal_url must not be blank")

    return {
        node_id: {
            "internal_url": internal_url,
            "supported_actions": actions,
            "priority_class": str(node.get("priority_class", "P2")).strip() or "P2",
            "max_concurrent": int(node.get("max_concurrent", 50)),
            "health_endpoint": str(node.get("health_endpoint", "/v1/health")).strip() or "/v1/health",
            "timeout_ms": int(node.get("timeout_ms", 30000)),
            "metadata": {
                "version": str(node.get("version", "1.0.0")).strip() or "1.0.0",
                "type": str(node.get("type", "custom")).strip() or "custom",
                "generated_by": "constellation-node-sdk",
            },
        }
    }


async def register_with_gate(
    *,
    gate_url: str,
    admin_token: str | None = None,
    spec_path: str,
    retries: int = 3,
    overwrite: bool = True,
) -> bool:
    """
    Register the current node with Gate via POST /v1/admin/register.

    Returns True on success, False on rejection or after retry exhaustion.
    Registration failure is intentionally non-fatal for node startup.
    """
    try:
        spec = load_node_spec(spec_path)
        payload = build_registration_payload(spec)
    except (FileNotFoundError, ValueError):
        return False

    node_id = next(iter(payload))
    url = f"{gate_url.rstrip('/')}/v1/admin/register"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if admin_token:
        headers["X-Admin-Token"] = admin_token
    params = {"overwrite": "true" if overwrite else "false"}

    for attempt in range(1, retries + 1):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers=headers,
                    params=params,
                )

            if response.status_code == 200:
                return True

            if response.status_code in {400, 401, 403, 409, 422}:
                return False

        except httpx.TransportError:
            pass

        if attempt < retries:
            backoff = _DEFAULT_RETRY_BASE_SECONDS * (2 ** (attempt - 1))
            await asyncio.sleep(backoff)

    return False


async def register_from_env() -> bool:
    """
    Convenience wrapper for Gate registration using environment-derived config.
    """
    config: GateRegistrationConfig = get_gate_registration_config_from_env()
    if not config.registration_enabled:
        return False

    return await register_with_gate(
        gate_url=config.gate_url,
        admin_token=config.admin_token,
        spec_path=config.spec_path,
        retries=config.retries,
        overwrite=config.overwrite,
    )
These four files now establish:

canonical node-side Gate client configuration

outbound policy enforcement for Gate-only routing

TransportPacket request/response transport over /v1/execute

self-registration from spec.yaml over /v1/admin/register

🚀 Your Next Prompt

Generate the Phase 1 runtime layer for constellation-node-sdk: complete runnable files for runtime/config.py, runtime/handlers.py, runtime/execution.py, and runtime/preflight.py, wired to the current TransportPacket, security layer, and Gate client, so a node can validate inbound packets, execute registered handlers, and produce canonical response packets.

Reply Y to use this as your next prompt!


Y

Strategic reasoning:

The next leverage point is the node runtime boundary. You now have a canonical TransportPacket, security validation, hop integrity, and a Gate-only client. What remains is the local execution shell that lets a node safely accept inbound transport, run registered handlers, and emit canonical responses. The smallest complete slice is exactly these four files: runtime config, handler registry, execution engine, and preflight. That gives you an installable node substrate without dragging in FastAPI app assembly yet.

# filename: src/constellation_node_sdk/runtime/config.py
from __future__ import annotations

import json
import os
from functools import lru_cache

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_ALLOWED_ENVIRONMENTS = {"local", "dev", "test", "staging", "prod"}
_ALLOWED_SIGNING_ALGORITHMS = {"hmac-sha256", "ed25519"}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_tuple(name: str) -> tuple[str, ...]:
    raw = os.getenv(name, "")
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _env_json_map(name: str) -> dict[str, str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError(f"{name} must be a JSON object")
    result: dict[str, str] = {}
    for key, value in parsed.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError(f"{name} must map strings to strings")
        result[key] = value
    return result


class NodeRuntimeConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    environment: str
    node_name: str
    service_name: str
    service_version: str

    dev_mode: bool = False
    require_signature: bool = False
    expose_internal_errors: bool = False
    return_transport_errors: bool = True

    signing_algorithm: str = "hmac-sha256"
    signing_key: str | None = None
    signing_private_key: str | None = None
    signing_key_id: str | None = None
    verifying_keys: dict[str, str] = Field(default_factory=dict)

    allowed_actions: tuple[str, ...] = ()
    allowed_packet_types: tuple[str, ...] = ("request", "command", "delegation", "replay_request")
    require_idempotency_for_actions: tuple[str, ...] = ()

    allowed_clock_skew_seconds: int = Field(default=30, ge=0)
    max_packet_bytes: int = Field(default=262_144, ge=1024)
    max_hop_depth: int = Field(default=64, ge=1)
    max_delegation_depth: int = Field(default=8, ge=1)
    max_attachments: int = Field(default=32, ge=0)
    max_attachment_size_bytes: int = Field(default=10_485_760, ge=0)
    attachment_allowed_schemes: tuple[str, ...] = ()
    allow_private_attachment_hosts: bool = False

    replay_enabled: bool = True
    verify_hop_signatures: bool = False

    gate_url: str | None = None
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)

    @field_validator(
        "environment",
        "node_name",
        "service_name",
        "service_version",
        "signing_algorithm",
        "host",
    )
    @classmethod
    def validate_required_strings(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_ENVIRONMENTS:
            raise ValueError(f"environment must be one of {sorted(_ALLOWED_ENVIRONMENTS)}")
        return normalized

    @field_validator("signing_algorithm")
    @classmethod
    def validate_signing_algorithm(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_SIGNING_ALGORITHMS:
            raise ValueError(f"signing_algorithm must be one of {sorted(_ALLOWED_SIGNING_ALGORITHMS)}")
        return normalized

    @field_validator(
        "allowed_actions",
        "allowed_packet_types",
        "require_idempotency_for_actions",
        "attachment_allowed_schemes",
    )
    @classmethod
    def validate_string_tuples(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip().lower() for item in value if item.strip())
        if len(set(normalized)) != len(normalized):
            raise ValueError("tuple entries must not contain duplicates")
        return normalized

    @field_validator("signing_key_id")
    @classmethod
    def validate_optional_key_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("signing_key_id must not be blank")
        return normalized

    @field_validator("verifying_keys")
    @classmethod
    def validate_verifying_keys(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for key_id, key_value in value.items():
            normalized_key = key_id.strip()
            normalized_value = key_value.strip()
            if not normalized_key or not normalized_value:
                raise ValueError("verifying_keys must not contain blank keys or values")
            normalized[normalized_key] = normalized_value
        return normalized

    @field_validator("gate_url")
    @classmethod
    def validate_gate_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().rstrip("/")
        if not normalized:
            raise ValueError("gate_url must not be blank")
        if not (normalized.startswith("http://") or normalized.startswith("https://")):
            raise ValueError("gate_url must start with http:// or https://")
        return normalized

    @model_validator(mode="after")
    def validate_security_profile(self) -> "NodeRuntimeConfig":
        if self.environment in {"staging", "prod"} and self.dev_mode:
            raise ValueError("dev_mode cannot be enabled in staging or prod")

        if self.require_signature:
            if self.signing_algorithm == "hmac-sha256" and not self.signing_key:
                raise ValueError("hmac-sha256 requires signing_key when require_signature=true")
            if self.signing_algorithm == "ed25519" and not self.signing_private_key:
                raise ValueError("ed25519 requires signing_private_key when require_signature=true")

        if self.signing_algorithm == "ed25519" and self.signing_key is not None:
            raise ValueError("signing_key must not be used with ed25519")

        invalid_idempotency = set(self.require_idempotency_for_actions) - set(self.allowed_actions)
        if invalid_idempotency:
            invalid = ", ".join(sorted(invalid_idempotency))
            raise ValueError(f"require_idempotency_for_actions contains unknown actions: {invalid}")

        if self.max_attachment_size_bytes > self.max_packet_bytes:
            raise ValueError("max_attachment_size_bytes must not exceed max_packet_bytes")

        if self.max_attachments > 0 and not self.attachment_allowed_schemes:
            raise ValueError("attachment_allowed_schemes must be configured when attachments are enabled")

        return self

    def resolve_verifying_key(self, key_id: str | None) -> str | bytes | None:
        if key_id is None:
            return None
        if key_id in self.verifying_keys:
            return self.verifying_keys[key_id]
        if self.signing_key_id is not None and key_id == self.signing_key_id:
            if self.signing_algorithm == "hmac-sha256":
                return self.signing_key
        return None


@lru_cache
def get_runtime_config() -> NodeRuntimeConfig:
    environment = os.getenv("L9_ENVIRONMENT", "local").strip().lower() or "local"
    dev_mode = _env_bool("L9_DEV_MODE", False)
    return NodeRuntimeConfig(
        environment=environment,
        node_name=os.getenv("L9_NODE_NAME", "unknown-node"),
        service_name=os.getenv("L9_SERVICE_NAME", os.getenv("L9_NODE_NAME", "unknown-node")),
        service_version=os.getenv("L9_SERVICE_VERSION", "1.0.0"),
        dev_mode=dev_mode,
        require_signature=_env_bool("L9_REQUIRE_SIGNATURE", False),
        expose_internal_errors=_env_bool("L9_EXPOSE_INTERNAL_ERRORS", False),
        return_transport_errors=_env_bool("L9_RETURN_TRANSPORT_ERRORS", True),
        signing_algorithm=os.getenv("L9_SIGNING_ALGORITHM", "hmac-sha256"),
        signing_key=os.getenv("L9_SIGNING_KEY") or os.getenv("L9_SIGNING_SECRET"),
        signing_private_key=os.getenv("L9_SIGNING_PRIVATE_KEY"),
        signing_key_id=os.getenv("L9_SIGNING_KEY_ID"),
        verifying_keys=_env_json_map("L9_VERIFYING_KEYS_JSON"),
        allowed_actions=_env_tuple("L9_ALLOWED_ACTIONS"),
        allowed_packet_types=_env_tuple("L9_ALLOWED_PACKET_TYPES") or ("request", "command", "delegation", "replay_request"),
        require_idempotency_for_actions=_env_tuple("L9_REQUIRE_IDEMPOTENCY_FOR_ACTIONS"),
        allowed_clock_skew_seconds=int(os.getenv("L9_ALLOWED_CLOCK_SKEW_SECONDS", "30")),
        max_packet_bytes=int(os.getenv("L9_MAX_PACKET_BYTES", "262144")),
        max_hop_depth=int(os.getenv("L9_MAX_HOP_DEPTH", "64")),
        max_delegation_depth=int(os.getenv("L9_MAX_DELEGATION_DEPTH", "8")),
        max_attachments=int(os.getenv("L9_MAX_ATTACHMENTS", "32")),
        max_attachment_size_bytes=int(os.getenv("L9_MAX_ATTACHMENT_SIZE_BYTES", "10485760")),
        attachment_allowed_schemes=_env_tuple("L9_ATTACHMENT_ALLOWED_SCHEMES"),
        allow_private_attachment_hosts=_env_bool("L9_ALLOW_PRIVATE_ATTACHMENT_HOSTS", False),
        replay_enabled=_env_bool("L9_REPLAY_ENABLED", True),
        verify_hop_signatures=_env_bool("L9_VERIFY_HOP_SIGNATURES", False),
        gate_url=os.getenv("GATE_URL"),
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
    )
# filename: src/constellation_node_sdk/runtime/handlers.py
from __future__ import annotations

from collections.abc import Callable
from typing import Any

_HANDLER_REGISTRY: dict[str, Callable[..., Any]] = {}


def register_handler(action: str, fn: Callable[..., Any] | None = None) -> Callable[..., Any]:
    """
    Register a runtime handler for a transport action.
    """
    normalized_action = action.strip().lower()
    if not normalized_action:
        raise ValueError("action must not be empty")

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        _HANDLER_REGISTRY[normalized_action] = func
        return func

    if fn is not None:
        return decorator(fn)
    return decorator


def get_handler(action: str) -> Callable[..., Any] | None:
    """
    Resolve a handler by exact action, falling back to '*' if present.
    """
    normalized_action = action.strip().lower()
    return _HANDLER_REGISTRY.get(normalized_action) or _HANDLER_REGISTRY.get("*")


def clear_handlers() -> None:
    """
    Clear all registered handlers.
    """
    _HANDLER_REGISTRY.clear()


def registered_actions() -> tuple[str, ...]:
    """
    Return the registered action names in sorted order.
    """
    return tuple(sorted(_HANDLER_REGISTRY.keys()))
# filename: src/constellation_node_sdk/runtime/execution.py
from __future__ import annotations

import asyncio
import base64
import inspect
from collections.abc import Callable

from cryptography.hazmat.primitives.serialization import load_pem_private_key

from constellation_node_sdk.security.signing import sign_transport_packet
from constellation_node_sdk.security.validation import validate_transport_packet
from constellation_node_sdk.transport.hop_trace import (
    make_execution_hop,
    make_response_hop,
)
from constellation_node_sdk.transport.packet import TransportPacket

from .handlers import get_handler


def _coerce_signing_key(signing_key: bytes | str | None, signing_private_key: str | None, signing_algorithm: str | None) -> bytes | str | None:
    """
    Resolve the appropriate signing key material for the configured algorithm.

    For HMAC: use signing_key.
    For Ed25519: use signing_private_key.
    """
    if signing_algorithm is None:
        return signing_key if signing_key is not None else signing_private_key

    normalized_algorithm = signing_algorithm.strip().lower()
    if normalized_algorithm == "hmac-sha256":
        return signing_key
    if normalized_algorithm == "ed25519":
        return signing_private_key
    raise ValueError(f"unsupported signing algorithm: {normalized_algorithm}")


def _default_key_resolver_from_hmac(signing_key: bytes | str | None) -> Callable[[str | None], str | bytes | None] | None:
    if signing_key is None:
        return None
    return lambda _key_id: signing_key


def _derive_public_key_from_private(signing_private_key: str) -> str:
    raw = signing_private_key.strip()
    if raw.startswith("-----BEGIN"):
        private_key = load_pem_private_key(raw.encode("utf-8"), password=None)
    else:
        try:
            decoded = base64.b64decode(raw, validate=True)
        except Exception:
            decoded = raw.encode("utf-8")
        private_key = load_pem_private_key(decoded, password=None) if decoded.startswith(b"-----BEGIN") else None
        if private_key is None:
            raise ValueError("ed25519 runtime verification requires PEM private key for local public-key derivation")

    public_key = private_key.public_key()
    pem = public_key.public_bytes(encoding=__import__("cryptography.hazmat.primitives.serialization", fromlist=["Encoding"]).Encoding.PEM, format=__import__("cryptography.hazmat.primitives.serialization", fromlist=["PublicFormat"]).PublicFormat.SubjectPublicKeyInfo)
    return pem.decode("utf-8")


def _ed25519_key_resolver(
    *,
    signing_private_key: str | None,
    signing_key_id: str | None,
    verifying_keys: dict[str, str],
) -> Callable[[str | None], str | bytes | None] | None:
    if verifying_keys:
        def resolver(key_id: str | None) -> str | bytes | None:
            if key_id is None:
                return None
            return verifying_keys.get(key_id)
        return resolver

    if signing_private_key is not None and signing_key_id is not None:
        derived_public_key = _derive_public_key_from_private(signing_private_key)

        def resolver(key_id: str | None) -> str | bytes | None:
            if key_id == signing_key_id:
                return derived_public_key
            return None

        return resolver

    return None


def _build_key_resolver(
    *,
    signing_algorithm: str | None,
    signing_key: bytes | str | None,
    signing_private_key: str | None,
    signing_key_id: str | None,
    verifying_keys: dict[str, str],
) -> Callable[[str | None], str | bytes | None] | None:
    if signing_algorithm is None:
        return None

    normalized_algorithm = signing_algorithm.strip().lower()
    if normalized_algorithm == "hmac-sha256":
        return _default_key_resolver_from_hmac(signing_key)
    if normalized_algorithm == "ed25519":
        return _ed25519_key_resolver(
            signing_private_key=signing_private_key,
            signing_key_id=signing_key_id,
            verifying_keys=verifying_keys,
        )
    raise ValueError(f"unsupported signing algorithm: {normalized_algorithm}")


async def _invoke_handler(handler: Callable[..., object], packet: TransportPacket) -> object:
    parameters = list(inspect.signature(handler).parameters.values())

    if len(parameters) == 1:
        candidate = handler(packet)
    elif len(parameters) == 2:
        candidate = handler(packet.tenant.org_id, packet.payload)
    elif len(parameters) == 0:
        candidate = handler()
    else:
        candidate = handler(packet.tenant.org_id, packet.payload, packet)

    if inspect.isawaitable(candidate):
        return await candidate
    return candidate


def _extract_payload(result: object) -> dict[str, object]:
    if isinstance(result, dict):
        return result
    raise TypeError(f"handler must return dict or TransportPacket, got {type(result)!r}")


async def execute_transport_packet(
    packet: TransportPacket,
    *,
    node_name: str,
    signing_key: bytes | str | None = None,
    signing_private_key: str | None = None,
    signing_key_id: str | None = None,
    signing_algorithm: str | None = None,
    verifying_keys: dict[str, str] | None = None,
    require_signature: bool = False,
    allowed_actions: tuple[str, ...] | None = None,
    allowed_packet_types: tuple[str, ...] | None = None,
    required_idempotency_actions: tuple[str, ...] | None = None,
    replay_enabled: bool = True,
    dev_mode: bool = False,
    verify_hop_signatures: bool = False,
    allowed_clock_skew_seconds: int = 30,
    max_packet_bytes: int = 262_144,
    max_hop_depth: int = 64,
    max_delegation_depth: int = 8,
    max_attachments: int = 32,
    max_attachment_size_bytes: int = 10_485_760,
    allowed_attachment_schemes: tuple[str, ...] = (),
    allow_private_attachment_hosts: bool = False,
) -> TransportPacket:
    """
    Validate, execute, and respond to a canonical inbound TransportPacket.
    """
    normalized_node_name = node_name.strip().lower()
    normalized_verifying_keys = verifying_keys or {}
    key_resolver = _build_key_resolver(
        signing_algorithm=signing_algorithm,
        signing_key=signing_key,
        signing_private_key=signing_private_key,
        signing_key_id=signing_key_id,
        verifying_keys=normalized_verifying_keys,
    )

    validate_transport_packet(
        packet,
        key_resolver=key_resolver,
        require_signature=require_signature,
        max_packet_bytes=max_packet_bytes,
        max_hop_depth=max_hop_depth,
        max_delegation_depth=max_delegation_depth,
        max_attachments=max_attachments,
        max_attachment_size_bytes=max_attachment_size_bytes,
        allowed_attachment_schemes=allowed_attachment_schemes,
        allow_private_attachment_hosts=allow_private_attachment_hosts,
        allowed_clock_skew_seconds=allowed_clock_skew_seconds,
        local_node=normalized_node_name,
        allowed_actions=allowed_actions,
        allowed_packet_types=allowed_packet_types,
        required_idempotency_actions=required_idempotency_actions,
        replay_enabled=replay_enabled,
        dev_mode=dev_mode,
        verify_hop_signatures=verify_hop_signatures,
        hop_key_resolver=key_resolver,
    )

    handler = get_handler(packet.header.action)
    if handler is None:
        raise ValueError(f"no handler registered for action: {packet.header.action}")

    processing_packet = packet.with_hop(
        make_execution_hop(
            packet=packet,
            node=normalized_node_name,
            action=packet.header.action,
            status="processing",
        )
    )

    try:
        result = await asyncio.wait_for(
            _invoke_handler(handler, processing_packet),
            timeout=processing_packet.header.timeout_ms / 1000,
        )
    except TimeoutError as exc:
        raise TimeoutError(f"handler timeout after {processing_packet.header.timeout_ms}ms") from exc

    if isinstance(result, TransportPacket):
        response_packet = result
    else:
        payload = _extract_payload(result)
        response_packet = processing_packet.derive(
            packet_type="response",
            source_node=normalized_node_name,
            destination_node=processing_packet.address.reply_to,
            reply_to=normalized_node_name,
            payload=payload,
        )

    response_packet = response_packet.with_hop(
        make_response_hop(
            packet=response_packet,
            node=normalized_node_name,
            action=response_packet.header.action,
            status=str(response_packet.payload.get("status", "completed")).strip().lower(),
        )
    )

    resolved_signing_key = _coerce_signing_key(signing_key, signing_private_key, signing_algorithm)
    if resolved_signing_key is not None:
        if signing_key_id is None or signing_algorithm is None:
            raise ValueError("signing_key_id and signing_algorithm are required when signing responses")
        response_packet = sign_transport_packet(
            response_packet,
            key=resolved_signing_key,
            key_id=signing_key_id,
            algorithm=signing_algorithm,
        )

    return response_packet


def create_error_transport_packet(
    packet: TransportPacket,
    error: Exception,
    *,
    node_name: str,
    signing_key: bytes | str | None = None,
    signing_private_key: str | None = None,
    signing_key_id: str | None = None,
    signing_algorithm: str | None = None,
    expose_internal_errors: bool = False,
) -> TransportPacket:
    """
    Build a canonical error response packet for a failed inbound request.
    """
    normalized_node_name = node_name.strip().lower()
    client_message = str(error) if expose_internal_errors else error.__class__.__name__

    response_packet = packet.derive(
        packet_type="failure",
        source_node=normalized_node_name,
        destination_node=packet.address.reply_to,
        reply_to=normalized_node_name,
        payload={
            "status": "failed",
            "error": error.__class__.__name__,
            "message": client_message,
            "packet_id": str(packet.header.packet_id),
        },
    )

    response_packet = response_packet.with_hop(
        make_response_hop(
            packet=response_packet,
            node=normalized_node_name,
            action=response_packet.header.action,
            status="failed",
            error_code=error.__class__.__name__,
            error_message=str(error) if expose_internal_errors else client_message,
        )
    )

    resolved_signing_key = _coerce_signing_key(signing_key, signing_private_key, signing_algorithm)
    if resolved_signing_key is not None:
        if signing_key_id is None or signing_algorithm is None:
            raise ValueError("signing_key_id and signing_algorithm are required when signing error responses")
        response_packet = sign_transport_packet(
            response_packet,
            key=resolved_signing_key,
            key_id=signing_key_id,
            algorithm=signing_algorithm,
        )

    return response_packet
# filename: src/constellation_node_sdk/runtime/preflight.py
from __future__ import annotations

from .config import NodeRuntimeConfig


class PreflightFailure(RuntimeError):
    """Raised when runtime configuration is not safe to start."""


def run_preflight(config: NodeRuntimeConfig) -> None:
    """
    Validate runtime configuration relationships before starting a node runtime.
    """
    _validate_security_profile(config)
    _validate_action_configuration(config)
    _validate_attachment_configuration(config)
    _validate_gate_configuration(config)


def _validate_security_profile(config: NodeRuntimeConfig) -> None:
    if config.dev_mode:
        return

    if not config.require_signature:
        return

    if config.signing_algorithm == "hmac-sha256":
        if not config.signing_key:
            raise PreflightFailure("hmac-sha256 requires signing_key when signatures are required")
        return

    if config.signing_algorithm == "ed25519":
        if not config.signing_private_key:
            raise PreflightFailure("ed25519 requires signing_private_key when signatures are required")
        return

    raise PreflightFailure(f"unsupported signing algorithm: {config.signing_algorithm}")


def _validate_action_configuration(config: NodeRuntimeConfig) -> None:
    allowed_actions = set(config.allowed_actions)
    required_idempotency = set(config.require_idempotency_for_actions)

    if required_idempotency and not allowed_actions:
        raise PreflightFailure(
            "require_idempotency_for_actions is configured but allowed_actions is empty"
        )

    if not required_idempotency.issubset(allowed_actions):
        invalid = sorted(required_idempotency - allowed_actions)
        joined = ", ".join(invalid)
        raise PreflightFailure(
            f"require_idempotency_for_actions contains actions not present in allowed_actions: {joined}"
        )

    if "response" in allowed_actions or "failure" in allowed_actions:
        raise PreflightFailure("allowed_actions must list executable inbound actions only, not response packet types")


def _validate_attachment_configuration(config: NodeRuntimeConfig) -> None:
    if config.max_attachment_size_bytes > config.max_packet_bytes:
        raise PreflightFailure("max_attachment_size_bytes must not exceed max_packet_bytes")

    if config.max_attachments > 0 and not config.attachment_allowed_schemes:
        raise PreflightFailure("attachment_allowed_schemes must be configured when attachments are enabled")


def _validate_gate_configuration(config: NodeRuntimeConfig) -> None:
    if config.gate_url is None:
        return
    if not (config.gate_url.startswith("http://") or config.gate_url.startswith("https://")):
        raise PreflightFailure("gate_url must start with http:// or https://")
These four files now give you the SDK-side node runtime contract:

NodeRuntimeConfig for inbound execution policy

handler registration and discovery

full inbound packet execution path

canonical success/failure response generation

preflight checks before runtime start

One important note: the current execution.py supports HMAC fully and supports Ed25519 signing when a private key is provided, but local Ed25519 inbound verification from a raw 32-byte private key is intentionally stricter because deriving a local public key without a proper configured verifying map is fragile. That is the right tradeoff for production correctness.

🚀 Your Next Prompt

Generate the Phase 1 runtime app layer for constellation-node-sdk: complete runnable files for runtime/lifecycle.py, runtime/observability.py, runtime/errors.py, and runtime/app.py, wiring FastAPI /v1/execute and /v1/health to execute_transport_packet() and create_error_transport_packet() with NodeRuntimeConfig, preflight, and optional Gate registration on startup.

Reply Y to use this as your next prompt!


Y

Strategic reasoning:

This is the correct next slice. You already have the runtime contract, handler registry, transport validation, error packet generation, and Gate client. The missing layer is the actual node app shell that turns those pieces into a runnable service with /v1/execute and /v1/health, plus startup preflight and optional Gate registration. That is the smallest complete boundary that makes the SDK installable and operational.

# filename: src/constellation_node_sdk/runtime/lifecycle.py
from __future__ import annotations

from abc import ABC, abstractmethod


class LifecycleHook(ABC):
    """
    Minimal lifecycle interface for node startup and shutdown hooks.
    """

    @abstractmethod
    async def startup(self) -> None:
        """Run node-specific startup logic."""

    @abstractmethod
    async def shutdown(self) -> None:
        """Run node-specific shutdown logic."""


class NoOpLifecycle(LifecycleHook):
    """
    Default lifecycle hook when a node has no custom startup or shutdown behavior.
    """

    async def startup(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None
# filename: src/constellation_node_sdk/runtime/observability.py
from __future__ import annotations

import logging
import sys

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, generate_latest
from pythonjsonlogger import jsonlogger
from starlette.responses import Response

from .config import NodeRuntimeConfig

REGISTRY = CollectorRegistry(auto_describe=True)
REQUESTS_TOTAL = Counter(
    "constellation_node_requests_total",
    "Total execute requests",
    ["service", "action", "status"],
    registry=REGISTRY,
)
READY_GAUGE = Gauge(
    "constellation_node_ready",
    "Service readiness",
    ["service"],
    registry=REGISTRY,
)


def configure_logging(config: NodeRuntimeConfig) -> None:
    """
    Configure root logging for the node runtime.
    """
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    root.addHandler(handler)


def set_readiness(*, config: NodeRuntimeConfig, ready: bool) -> None:
    """
    Update readiness gauge for the current service.
    """
    READY_GAUGE.labels(service=config.service_name).set(1 if ready else 0)


def record_request(*, config: NodeRuntimeConfig, action: str, status: str) -> None:
    """
    Increment request counter for an executed action.
    """
    REQUESTS_TOTAL.labels(
        service=config.service_name,
        action=action.strip().lower(),
        status=status.strip().lower(),
    ).inc()


def metrics_response() -> Response:
    """
    Return the Prometheus metrics payload.
    """
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
# filename: src/constellation_node_sdk/runtime/errors.py
from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException


@dataclass(frozen=True)
class RuntimeErrorDetail:
    code: str
    message: str
    status_code: int


def classify_exception(exc: Exception) -> RuntimeErrorDetail:
    """
    Map runtime exceptions to safe HTTP-facing error details.
    """
    if isinstance(exc, ValueError):
        return RuntimeErrorDetail(
            code="invalid_request",
            message=str(exc),
            status_code=400,
        )

    if isinstance(exc, TimeoutError):
        return RuntimeErrorDetail(
            code="execution_timeout",
            message="handler execution timed out",
            status_code=504,
        )

    return RuntimeErrorDetail(
        code="internal_error",
        message="internal server error",
        status_code=500,
    )


def raise_http_exception(exc: Exception) -> None:
    """
    Raise a FastAPI HTTPException from a classified runtime exception.
    """
    detail = classify_exception(exc)
    raise HTTPException(
        status_code=detail.status_code,
        detail={
            "code": detail.code,
            "message": detail.message,
        },
    ) from exc
# filename: src/constellation_node_sdk/runtime/app.py
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from constellation_node_sdk.gate.registration import register_from_env

from .config import NodeRuntimeConfig, get_runtime_config
from .errors import raise_http_exception
from .execution import create_error_transport_packet, execute_transport_packet
from .lifecycle import LifecycleHook, NoOpLifecycle
from .observability import configure_logging, metrics_response, record_request, set_readiness
from .preflight import run_preflight
from ..transport.packet import TransportPacket


def _key_material_from_config(config: NodeRuntimeConfig) -> tuple[bytes | str | None, str | None]:
    """
    Resolve response signing material from runtime config.

    HMAC uses signing_key.
    Ed25519 uses signing_private_key.
    """
    if config.signing_algorithm == "hmac-sha256":
        return config.signing_key, config.signing_algorithm
    if config.signing_algorithm == "ed25519":
        return config.signing_private_key, config.signing_algorithm
    return None, None


def create_node_app(
    *,
    service_name: str | None = None,
    version: str | None = None,
    lifecycle_hook: LifecycleHook | None = None,
    config: NodeRuntimeConfig | None = None,
    auto_register_with_gate: bool = True,
) -> FastAPI:
    """
    Create a packet-native FastAPI node runtime.

    Endpoints:
    - POST /v1/execute
    - GET  /v1/health
    - GET  /metrics
    """
    resolved_config = config or get_runtime_config()
    resolved_service_name = service_name or resolved_config.service_name
    resolved_version = version or resolved_config.service_version
    resolved_lifecycle = lifecycle_hook or NoOpLifecycle()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging(resolved_config)
        run_preflight(resolved_config)

        app.state.runtime_ready = False
        set_readiness(config=resolved_config, ready=False)

        await resolved_lifecycle.startup()

        if auto_register_with_gate and resolved_config.gate_url:
            await register_from_env()

        app.state.runtime_ready = True
        set_readiness(config=resolved_config, ready=True)

        yield

        app.state.runtime_ready = False
        set_readiness(config=resolved_config, ready=False)
        await resolved_lifecycle.shutdown()

    app = FastAPI(
        title=resolved_service_name,
        version=resolved_version,
        lifespan=lifespan,
    )
    app.state.runtime_ready = False

    @app.get("/v1/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "healthy" if bool(getattr(app.state, "runtime_ready", False)) else "starting",
            "service_name": resolved_config.service_name,
            "service_version": resolved_config.service_version,
            "node_name": resolved_config.node_name,
            "ready": bool(getattr(app.state, "runtime_ready", False)),
        }

    @app.get("/metrics")
    async def metrics():
        return metrics_response()

    @app.post("/v1/execute")
    async def execute(request: Request):
        packet: TransportPacket | None = None
        try:
            body = await request.json()
        except Exception as exc:
            record_request(config=resolved_config, action="unknown", status="invalid_json")
            raise HTTPException(status_code=400, detail=f"invalid JSON body: {exc}") from exc

        try:
            if not isinstance(body, dict):
                raise ValueError("request body must be a JSON object")

            packet = TransportPacket.model_validate(body)

            response_signing_key, response_signing_algorithm = _key_material_from_config(resolved_config)

            response_packet = await execute_transport_packet(
                packet,
                node_name=resolved_config.node_name,
                signing_key=response_signing_key if response_signing_algorithm == "hmac-sha256" else None,
                signing_private_key=response_signing_key if response_signing_algorithm == "ed25519" else None,
                signing_key_id=resolved_config.signing_key_id,
                signing_algorithm=response_signing_algorithm,
                verifying_keys=resolved_config.verifying_keys,
                require_signature=resolved_config.require_signature,
                allowed_actions=resolved_config.allowed_actions or None,
                allowed_packet_types=resolved_config.allowed_packet_types or None,
                required_idempotency_actions=resolved_config.require_idempotency_for_actions or None,
                replay_enabled=resolved_config.replay_enabled,
                dev_mode=resolved_config.dev_mode,
                verify_hop_signatures=resolved_config.verify_hop_signatures,
                allowed_clock_skew_seconds=resolved_config.allowed_clock_skew_seconds,
                max_packet_bytes=resolved_config.max_packet_bytes,
                max_hop_depth=resolved_config.max_hop_depth,
                max_delegation_depth=resolved_config.max_delegation_depth,
                max_attachments=resolved_config.max_attachments,
                max_attachment_size_bytes=resolved_config.max_attachment_size_bytes,
                allowed_attachment_schemes=resolved_config.attachment_allowed_schemes,
                allow_private_attachment_hosts=resolved_config.allow_private_attachment_hosts,
            )

            status = str(response_packet.payload.get("status", "completed")).strip().lower()
            record_request(config=resolved_config, action=packet.header.action, status=status)
            return JSONResponse(content=response_packet.model_dump_json_dict())

        except Exception as exc:
            if packet is not None and resolved_config.return_transport_errors:
                response_signing_key, response_signing_algorithm = _key_material_from_config(resolved_config)
                failure_packet = create_error_transport_packet(
                    packet,
                    exc,
                    node_name=resolved_config.node_name,
                    signing_key=response_signing_key if response_signing_algorithm == "hmac-sha256" else None,
                    signing_private_key=response_signing_key if response_signing_algorithm == "ed25519" else None,
                    signing_key_id=resolved_config.signing_key_id,
                    signing_algorithm=response_signing_algorithm,
                    expose_internal_errors=resolved_config.expose_internal_errors,
                )
                record_request(
                    config=resolved_config,
                    action=packet.header.action,
                    status="failed",
                )
                return JSONResponse(content=failure_packet.model_dump_json_dict())

            record_request(
                config=resolved_config,
                action="unknown" if packet is None else packet.header.action,
                status="error",
            )
            raise_http_exception(exc)

    return app
This app layer gives you:

lifecycle-managed startup and shutdown

preflight validation before traffic

optional self-registration with Gate on startup

packet-native /v1/execute

health and metrics endpoints

canonical failure-packet behavior for runtime exceptions

One implementation note: /metrics is always present in this version. If you want strict parity with prior env-gated metrics behavior, that should be a small follow-up in runtime/config.py plus one branch in runtime/app.py.

🚀 Your Next Prompt

Generate the Phase 1 package wiring files for constellation-node-sdk: complete runnable files for src/constellation_node_sdk/__init__.py, transport/__init__.py, security/__init__.py, gate/__init__.py, and runtime/__init__.py, exporting the canonical public API around TransportPacket, signing/validation, Gate client, and node app creation.

Reply Y to use this as your next prompt!


Can u 2-3x # of files per pass 🙏

Yes.

I can switch from 4-file slices to 8–12-file passes as the default, and go a bit larger when the files are tightly coupled.

Best cadence from here:

Pass size: 8–12 files

Rule: one coherent layer per pass, not mixed unrelated layers

Format: complete runnable files only

Recommended grouping:

package wiring + remaining __init__ exports + small support files

orchestrator layer in one pass

Gate config + schemas + boundary codec/policy/validator in one pass

Gate routing layer in one pass

Gate services + API app in one pass

tests in larger bundles by layer

That gives you a much faster build velocity without turning each pass into an unreviewable blob.

For the next pass, I recommend bundling:

src/constellation_node_sdk/__init__.py

src/constellation_node_sdk/transport/__init__.py

src/constellation_node_sdk/security/__init__.py

src/constellation_node_sdk/gate/__init__.py

src/constellation_node_sdk/runtime/__init__.py

src/constellation_node_sdk/orchestrator/__init__.py

src/constellation_node_sdk/runtime/errors.py

src/constellation_node_sdk/gate/errors.py

src/constellation_node_sdk/security/errors.py

src/constellation_node_sdk/runtime/lifecycle.py

Then the pass after that can do the full orchestrator layer in one shot.

🚀 Your Next Prompt

Generate a 10-file pass for constellation-node-sdk covering package wiring and support exports: complete runnable files for src/constellation_node_sdk/__init__.py, transport/__init__.py, security/__init__.py, gate/__init__.py, runtime/__init__.py, orchestrator/__init__.py, runtime/errors.py, gate/errors.py, security/errors.py, and runtime/lifecycle.py, with a clean public API centered on TransportPacket, validation, Gate client, and node app creation.

Reply Y to use this as your next prompt!


Y

Strategic reasoning:

This 10-file pass is the right acceleration point: it does not add new architecture, but it stabilizes the package surface so the SDK becomes importable, legible, and usable as a real library. That is high-leverage because it turns the transport/security/runtime work you already have into a coherent public API without reopening protocol decisions.

# filename: src/constellation_node_sdk/__init__.py
from __future__ import annotations

from constellation_node_sdk.gate import (
    GateClient,
    GateClientConfig,
    GateRegistrationConfig,
    assert_gate_only_destination,
    assert_local_node_identity,
    assert_node_origin_packet,
    build_registration_payload,
    get_gate_client_config_from_env,
    get_gate_registration_config_from_env,
    load_node_spec,
    register_from_env,
    register_with_gate,
    validate_outbound_gate_packet,
)
from constellation_node_sdk.runtime import (
    LifecycleHook,
    NoOpLifecycle,
    NodeRuntimeConfig,
    PreflightFailure,
    clear_handlers,
    create_error_transport_packet,
    create_node_app,
    execute_transport_packet,
    get_handler,
    get_runtime_config,
    register_handler,
    registered_actions,
    run_preflight,
)
from constellation_node_sdk.security import (
    recompute_transport_core,
    sign_transport_packet,
    validate_derived_transport_packet,
    validate_transport_packet,
    verify_transport_packet_signature,
)
from constellation_node_sdk.transport import (
    DelegationLink,
    RoutingProvenance,
    TenantContext,
    TransportAddress,
    TransportAttachment,
    TransportAuthenticationError,
    TransportAuthorizationError,
    TransportError,
    TransportExpiredError,
    TransportGovernance,
    TransportHeader,
    TransportHop,
    TransportIntegrityError,
    TransportLineage,
    TransportNotYetValidError,
    TransportPacket,
    TransportSecurity,
    TransportValidationError,
    canonical_json,
    compute_payload_hash,
    compute_transport_hash,
    create_transport_packet,
    ensure_tenant_context,
    utc_now,
)

__all__ = [
    "DelegationLink",
    "GateClient",
    "GateClientConfig",
    "GateRegistrationConfig",
    "LifecycleHook",
    "NoOpLifecycle",
    "NodeRuntimeConfig",
    "PreflightFailure",
    "RoutingProvenance",
    "TenantContext",
    "TransportAddress",
    "TransportAttachment",
    "TransportAuthenticationError",
    "TransportAuthorizationError",
    "TransportError",
    "TransportExpiredError",
    "TransportGovernance",
    "TransportHeader",
    "TransportHop",
    "TransportIntegrityError",
    "TransportLineage",
    "TransportNotYetValidError",
    "TransportPacket",
    "TransportSecurity",
    "TransportValidationError",
    "assert_gate_only_destination",
    "assert_local_node_identity",
    "assert_node_origin_packet",
    "build_registration_payload",
    "canonical_json",
    "clear_handlers",
    "compute_payload_hash",
    "compute_transport_hash",
    "create_error_transport_packet",
    "create_node_app",
    "create_transport_packet",
    "ensure_tenant_context",
    "execute_transport_packet",
    "get_gate_client_config_from_env",
    "get_gate_registration_config_from_env",
    "get_handler",
    "get_runtime_config",
    "load_node_spec",
    "recompute_transport_core",
    "register_from_env",
    "register_handler",
    "register_with_gate",
    "registered_actions",
    "run_preflight",
    "sign_transport_packet",
    "utc_now",
    "validate_derived_transport_packet",
    "validate_outbound_gate_packet",
    "validate_transport_packet",
    "verify_transport_packet_signature",
]
# filename: src/constellation_node_sdk/transport/__init__.py
from __future__ import annotations

from constellation_node_sdk.transport.errors import (
    PacketSizeError,
    SchemaVersionError,
    TenantMutationError,
    TransportAuthenticationError,
    TransportAuthorizationError,
    TransportError,
    TransportExpiredError,
    TransportIntegrityError,
    TransportNotYetValidError,
    TransportValidationError,
)
from constellation_node_sdk.transport.hashing import canonical_json, compute_payload_hash, compute_transport_hash
from constellation_node_sdk.transport.hop_trace import (
    compute_hop_hash,
    last_hop_hash,
    make_dispatch_hop,
    make_execution_hop,
    make_ingress_hop,
    make_response_hop,
    sign_hop,
    validate_hop_trace,
    verify_hop_signature,
)
from constellation_node_sdk.transport.models import (
    DelegationLink,
    TransportAddress,
    TransportAttachment,
    TransportGovernance,
    TransportHeader,
    TransportHop,
    TransportLineage,
    TransportSecurity,
    utc_now,
)
from constellation_node_sdk.transport.packet import TransportPacket, create_transport_packet
from constellation_node_sdk.transport.provenance import RoutingProvenance
from constellation_node_sdk.transport.tenant import (
    TenantContext,
    assert_tenant_immutable,
    ensure_tenant_context,
)

__all__ = [
    "DelegationLink",
    "PacketSizeError",
    "RoutingProvenance",
    "SchemaVersionError",
    "TenantContext",
    "TenantMutationError",
    "TransportAddress",
    "TransportAttachment",
    "TransportAuthenticationError",
    "TransportAuthorizationError",
    "TransportError",
    "TransportExpiredError",
    "TransportGovernance",
    "TransportHeader",
    "TransportHop",
    "TransportIntegrityError",
    "TransportLineage",
    "TransportNotYetValidError",
    "TransportPacket",
    "TransportSecurity",
    "TransportValidationError",
    "assert_tenant_immutable",
    "canonical_json",
    "compute_hop_hash",
    "compute_payload_hash",
    "compute_transport_hash",
    "create_transport_packet",
    "ensure_tenant_context",
    "last_hop_hash",
    "make_dispatch_hop",
    "make_execution_hop",
    "make_ingress_hop",
    "make_response_hop",
    "sign_hop",
    "utc_now",
    "validate_hop_trace",
    "verify_hop_signature",
]
# filename: src/constellation_node_sdk/security/__init__.py
from __future__ import annotations

from constellation_node_sdk.security.delegation import compute_delegation_proof
from constellation_node_sdk.security.errors import (
    SecurityError,
    TransportAuthenticationError,
    TransportAuthorizationError,
    TransportExpiredError,
    TransportIntegrityError,
    TransportNotYetValidError,
    TransportValidationError,
)
from constellation_node_sdk.security.signing import recompute_transport_core, sign_transport_packet
from constellation_node_sdk.security.validation import (
    transport_packet_size_bytes,
    validate_derived_transport_packet,
    validate_transport_packet,
)
from constellation_node_sdk.security.verification import verify_transport_packet_signature

__all__ = [
    "SecurityError",
    "TransportAuthenticationError",
    "TransportAuthorizationError",
    "TransportExpiredError",
    "TransportIntegrityError",
    "TransportNotYetValidError",
    "TransportValidationError",
    "compute_delegation_proof",
    "recompute_transport_core",
    "sign_transport_packet",
    "transport_packet_size_bytes",
    "validate_derived_transport_packet",
    "validate_transport_packet",
    "verify_transport_packet_signature",
]
# filename: src/constellation_node_sdk/gate/__init__.py
from __future__ import annotations

from constellation_node_sdk.gate.client import GateClient
from constellation_node_sdk.gate.config import (
    GateClientConfig,
    GateRegistrationConfig,
    get_gate_client_config_from_env,
    get_gate_registration_config_from_env,
)
from constellation_node_sdk.gate.errors import (
    GateClientError,
    GatePolicyError,
    GateRegistrationError,
    GateResponseError,
)
from constellation_node_sdk.gate.policy import (
    assert_gate_only_destination,
    assert_local_node_identity,
    assert_node_origin_packet,
    validate_outbound_gate_packet,
)
from constellation_node_sdk.gate.registration import (
    build_registration_payload,
    load_node_spec,
    register_from_env,
    register_with_gate,
)

__all__ = [
    "GateClient",
    "GateClientConfig",
    "GateClientError",
    "GatePolicyError",
    "GateRegistrationConfig",
    "GateRegistrationError",
    "GateResponseError",
    "assert_gate_only_destination",
    "assert_local_node_identity",
    "assert_node_origin_packet",
    "build_registration_payload",
    "get_gate_client_config_from_env",
    "get_gate_registration_config_from_env",
    "load_node_spec",
    "register_from_env",
    "register_with_gate",
    "validate_outbound_gate_packet",
]
# filename: src/constellation_node_sdk/runtime/__init__.py
from __future__ import annotations

from constellation_node_sdk.runtime.app import create_node_app
from constellation_node_sdk.runtime.config import NodeRuntimeConfig, get_runtime_config
from constellation_node_sdk.runtime.errors import (
    RuntimeConfigurationError,
    RuntimeErrorDetail,
    RuntimeExecutionError,
    RuntimeValidationError,
    classify_exception,
    raise_http_exception,
)
from constellation_node_sdk.runtime.execution import (
    create_error_transport_packet,
    execute_transport_packet,
)
from constellation_node_sdk.runtime.handlers import (
    clear_handlers,
    get_handler,
    register_handler,
    registered_actions,
)
from constellation_node_sdk.runtime.lifecycle import LifecycleHook, NoOpLifecycle
from constellation_node_sdk.runtime.preflight import PreflightFailure, run_preflight

__all__ = [
    "LifecycleHook",
    "NoOpLifecycle",
    "NodeRuntimeConfig",
    "PreflightFailure",
    "RuntimeConfigurationError",
    "RuntimeErrorDetail",
    "RuntimeExecutionError",
    "RuntimeValidationError",
    "classify_exception",
    "clear_handlers",
    "create_error_transport_packet",
    "create_node_app",
    "execute_transport_packet",
    "get_handler",
    "get_runtime_config",
    "raise_http_exception",
    "register_handler",
    "registered_actions",
    "run_preflight",
]
# filename: src/constellation_node_sdk/orchestrator/__init__.py
from __future__ import annotations

__all__: list[str] = []
# filename: src/constellation_node_sdk/runtime/errors.py
from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException

from constellation_node_sdk.transport.errors import (
    PacketSizeError,
    SchemaVersionError,
    TenantMutationError,
    TransportAuthenticationError,
    TransportAuthorizationError,
    TransportExpiredError,
    TransportIntegrityError,
    TransportNotYetValidError,
    TransportValidationError,
)


class RuntimeErrorBase(Exception):
    """Base exception for runtime-layer failures."""


class RuntimeConfigurationError(RuntimeErrorBase):
    """Raised when runtime configuration is invalid or incomplete."""


class RuntimeValidationError(RuntimeErrorBase):
    """Raised when an inbound request fails runtime validation."""


class RuntimeExecutionError(RuntimeErrorBase):
    """Raised when handler execution fails within the runtime shell."""


@dataclass(frozen=True)
class RuntimeErrorDetail:
    code: str
    message: str
    status_code: int


def classify_exception(exc: Exception) -> RuntimeErrorDetail:
    """
    Map runtime and transport exceptions to safe HTTP-facing error details.
    """
    if isinstance(
        exc,
        (
            ValueError,
            TransportValidationError,
            TransportIntegrityError,
            PacketSizeError,
            SchemaVersionError,
            TenantMutationError,
        ),
    ):
        return RuntimeErrorDetail(
            code="invalid_request",
            message=str(exc),
            status_code=400,
        )

    if isinstance(exc, (TransportAuthenticationError,)):
        return RuntimeErrorDetail(
            code="authentication_failed",
            message="transport authentication failed",
            status_code=401,
        )

    if isinstance(exc, (TransportAuthorizationError,)):
        return RuntimeErrorDetail(
            code="authorization_failed",
            message="transport authorization failed",
            status_code=403,
        )

    if isinstance(exc, (TransportExpiredError, TransportNotYetValidError)):
        return RuntimeErrorDetail(
            code="temporal_validity_failed",
            message=str(exc),
            status_code=409,
        )

    if isinstance(exc, TimeoutError):
        return RuntimeErrorDetail(
            code="execution_timeout",
            message="handler execution timed out",
            status_code=504,
        )

    return RuntimeErrorDetail(
        code="internal_error",
        message="internal server error",
        status_code=500,
    )


def raise_http_exception(exc: Exception) -> None:
    """
    Raise a FastAPI HTTPException from a classified runtime exception.
    """
    detail = classify_exception(exc)
    raise HTTPException(
        status_code=detail.status_code,
        detail={
            "code": detail.code,
            "message": detail.message,
        },
    ) from exc
# filename: src/constellation_node_sdk/gate/errors.py
from __future__ import annotations


class GateClientError(Exception):
    """Base exception for Gate client failures."""


class GatePolicyError(GateClientError):
    """Raised when an outbound packet violates Gate-only routing policy."""


class GateResponseError(GateClientError):
    """Raised when Gate returns an invalid or non-canonical response."""


class GateRegistrationError(GateClientError):
    """Raised when Gate registration cannot be completed safely."""
# filename: src/constellation_node_sdk/security/errors.py
from __future__ import annotations

from constellation_node_sdk.transport.errors import (
    TransportAuthenticationError,
    TransportAuthorizationError,
    TransportExpiredError,
    TransportIntegrityError,
    TransportNotYetValidError,
    TransportValidationError,
)


class SecurityError(Exception):
    """Base exception for the SDK security layer."""


__all__ = [
    "SecurityError",
    "TransportAuthenticationError",
    "TransportAuthorizationError",
    "TransportExpiredError",
    "TransportIntegrityError",
    "TransportNotYetValidError",
    "TransportValidationError",
]
# filename: src/constellation_node_sdk/runtime/lifecycle.py
from __future__ import annotations

from abc import ABC, abstractmethod


class LifecycleHook(ABC):
    """
    Minimal lifecycle interface for node startup and shutdown hooks.
    """

    @abstractmethod
    async def startup(self) -> None:
        """Run node-specific startup logic."""

    @abstractmethod
    async def shutdown(self) -> None:
        """Run node-specific shutdown logic."""


class NoOpLifecycle(LifecycleHook):
    """
    Default lifecycle hook when a node has no custom startup or shutdown behavior.
    """

    async def startup(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None
This pass gives you:

a coherent top-level SDK API

stable package exports by layer

reusable runtime/gate/security error surfaces

import-safe library wiring for the files already generated

🚀 Your Next Prompt

Generate a 9-file pass for constellation-node-sdk covering the full orchestrator layer: complete runnable files for orchestrator/base.py, orchestrator/state.py, orchestrator/retry.py, orchestrator/merge.py, orchestrator/packet_builder.py, orchestrator/step_executor.py, plus tests/orchestrator/test_packet_builder.py, tests/orchestrator/test_merge.py, and tests/orchestrator/test_retry.py, all centered on composing worker calls strictly back through Gate using TransportPacket.

Reply Y to use this as your next prompt!


Y-> Top Frontier AI Lab, enterprise-grade, production-ready, L9 repo aligned quality! 


Thought for 23s
Strategic reasoning:

You asked for a higher bar, so this pass is tightened toward enterprise-grade library quality: stronger invariants, stricter typing, explicit workflow state, deterministic merge behavior, retry policy that is predictable under load, and orchestrator execution that preserves the architectural law that all composed work goes back through Gate. This stays aligned with the L9 direction while keeping the pass coherent and reviewable.

# filename: src/constellation_node_sdk/orchestrator/base.py
from __future__ import annotations

from abc import ABC, abstractmethod

from constellation_node_sdk.gate.client import GateClient
from constellation_node_sdk.transport.packet import TransportPacket

from .state import OrchestratorState
from .step_executor import StepExecutor


class BaseOrchestrator(ABC):
    """
    Base class for packet-native orchestrators.

    Orchestrators are stateful internal clients of Gate. They never resolve
    peer nodes directly and never send step packets to peer URLs.
    """

    def __init__(self, *, gate_client: GateClient, source_node: str) -> None:
        normalized_source = source_node.strip().lower()
        if not normalized_source:
            raise ValueError("source_node must not be empty")

        self._gate_client = gate_client
        self._source_node = normalized_source
        self._step_executor = StepExecutor(
            gate_client=gate_client,
            source_node=normalized_source,
        )

    @property
    def gate_client(self) -> GateClient:
        return self._gate_client

    @property
    def source_node(self) -> str:
        return self._source_node

    @property
    def step_executor(self) -> StepExecutor:
        return self._step_executor

    def initial_state(self, packet: TransportPacket) -> OrchestratorState:
        """
        Build the default initial workflow state from the inbound packet.
        """
        return OrchestratorState.from_packet(
            packet=packet,
            orchestrator_node=self._source_node,
        )

    @abstractmethod
    async def execute(self, packet: TransportPacket) -> TransportPacket:
        """
        Execute the orchestrator workflow and return a canonical response packet.
        """
# filename: src/constellation_node_sdk/orchestrator/state.py
from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from constellation_node_sdk.transport.packet import TransportPacket


class OrchestratorState(BaseModel):
    """
    Immutable-ish workflow state container for orchestrators.

    The orchestrator owns workflow-local accumulation state. Gate owns routing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    root_id: UUID
    current_packet_id: UUID
    current_generation: int = Field(ge=0)
    orchestrator_node: str
    workflow_name: str | None = None
    accumulated_payload: dict[str, Any] = Field(default_factory=dict)
    step_results: tuple[dict[str, Any], ...] = ()
    completed_steps: tuple[str, ...] = ()
    failed_steps: tuple[str, ...] = ()

    @classmethod
    def from_packet(
        cls,
        *,
        packet: TransportPacket,
        orchestrator_node: str,
        workflow_name: str | None = None,
    ) -> "OrchestratorState":
        return cls(
            root_id=packet.lineage.root_id,
            current_packet_id=packet.header.packet_id,
            current_generation=packet.lineage.generation,
            orchestrator_node=orchestrator_node.strip().lower(),
            workflow_name=None if workflow_name is None else workflow_name.strip(),
            accumulated_payload=dict(packet.payload),
            step_results=(),
            completed_steps=(),
            failed_steps=(),
        )

    def with_step_success(
        self,
        *,
        step_name: str,
        response_packet: TransportPacket,
        merged_payload: dict[str, Any],
    ) -> "OrchestratorState":
        response_snapshot = {
            "step_name": step_name.strip().lower(),
            "packet_id": str(response_packet.header.packet_id),
            "action": response_packet.header.action,
            "payload": dict(response_packet.payload),
        }
        return self.model_copy(
            update={
                "current_packet_id": response_packet.header.packet_id,
                "current_generation": response_packet.lineage.generation,
                "accumulated_payload": dict(merged_payload),
                "step_results": self.step_results + (response_snapshot,),
                "completed_steps": self.completed_steps + (step_name.strip().lower(),),
            }
        )

    def with_step_failure(self, *, step_name: str) -> "OrchestratorState":
        return self.model_copy(
            update={
                "failed_steps": self.failed_steps + (step_name.strip().lower(),),
            }
        )
# filename: src/constellation_node_sdk/orchestrator/retry.py
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RetryPolicy(BaseModel):
    """
    Deterministic retry policy for orchestrator step execution.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_attempts: int = Field(default=3, ge=1)
    initial_delay_seconds: float = Field(default=0.25, ge=0.0)
    backoff_multiplier: float = Field(default=2.0, ge=1.0)
    max_delay_seconds: float = Field(default=5.0, ge=0.0)
    retryable_error_types: tuple[str, ...] = (
        "TimeoutError",
        "TransportAuthenticationError",
        "TransportAuthorizationError",
        "TransportValidationError",
        "TransportIntegrityError",
        "GateClientError",
    )

    @field_validator("retryable_error_types")
    @classmethod
    def validate_retryable_error_types(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in value if item.strip())
        if len(set(normalized)) != len(normalized):
            raise ValueError("retryable_error_types must not contain duplicates")
        return normalized

    def delay_for_attempt(self, attempt: int) -> float:
        """
        Return the backoff delay for the next retry after `attempt`.
        """
        if attempt < 1:
            raise ValueError("attempt must be >= 1")
        if self.max_attempts <= 1:
            return 0.0

        delay = self.initial_delay_seconds * (self.backoff_multiplier ** (attempt - 1))
        return min(delay, self.max_delay_seconds)


def should_retry(*, attempt: int, error: Exception, policy: RetryPolicy) -> bool:
    """
    Return True when the given error should be retried under the policy.

    `attempt` is 1-indexed and represents the attempt that just failed.
    """
    if attempt < 1:
        raise ValueError("attempt must be >= 1")

    if attempt >= policy.max_attempts:
        return False

    error_type_names = {cls.__name__ for cls in type(error).mro()}
    retryable = set(policy.retryable_error_types)
    return bool(error_type_names & retryable)
# filename: src/constellation_node_sdk/orchestrator/merge.py
from __future__ import annotations

from typing import Any

from constellation_node_sdk.transport.packet import TransportPacket


def _payload_copy(packet: TransportPacket) -> dict[str, Any]:
    return dict(packet.payload)


def _response_payload(response: TransportPacket) -> dict[str, Any]:
    return dict(response.payload)


def merge_identity(current: TransportPacket, response: TransportPacket) -> dict[str, Any]:
    """
    Replace accumulated payload with the full response payload.
    """
    del current
    return _response_payload(response)


def merge_results(current: TransportPacket, response: TransportPacket) -> dict[str, Any]:
    """
    Merge response.payload["data"] into current payload when present.
    Fall back to merging the full response payload.
    """
    merged = _payload_copy(current)
    response_payload = _response_payload(response)

    response_data = response_payload.get("data")
    if isinstance(response_data, dict):
        merged.update(response_data)
        return merged

    merged.update(response_payload)
    return merged


def merge_payload(current: TransportPacket, response: TransportPacket) -> dict[str, Any]:
    """
    Merge the full response payload into current payload.
    """
    merged = _payload_copy(current)
    merged.update(_response_payload(response))
    return merged
# filename: src/constellation_node_sdk/orchestrator/packet_builder.py
from __future__ import annotations

from typing import Any

from constellation_node_sdk.transport.packet import TransportPacket
from constellation_node_sdk.transport.provenance import RoutingProvenance


def build_step_packet(
    *,
    parent: TransportPacket,
    action: str,
    payload: dict[str, Any],
    source_node: str,
    reply_to: str,
) -> TransportPacket:
    """
    Build a child step packet for orchestrator -> Gate execution.

    This function enforces the architectural constraint that every step packet
    emitted by an orchestrator targets Gate, never a peer node.
    """
    normalized_action = action.strip().lower()
    if not normalized_action:
        raise ValueError("action must not be empty")

    normalized_source = source_node.strip().lower()
    normalized_reply_to = reply_to.strip().lower()
    if not normalized_source:
        raise ValueError("source_node must not be empty")
    if not normalized_reply_to:
        raise ValueError("reply_to must not be empty")

    provenance = RoutingProvenance(
        origin_kind="node",
        requested_action=normalized_action,
        resolved_by_gate=False,
        original_source_node=normalized_source,
    )

    return parent.derive(
        packet_type="request",
        action=normalized_action,
        source_node=normalized_source,
        destination_node="gate",
        reply_to=normalized_reply_to,
        payload=dict(payload),
        provenance=provenance,
    )
# filename: src/constellation_node_sdk/orchestrator/step_executor.py
from __future__ import annotations

import asyncio
from typing import Any

from constellation_node_sdk.gate.client import GateClient
from constellation_node_sdk.transport.packet import TransportPacket

from .packet_builder import build_step_packet
from .retry import RetryPolicy, should_retry


class StepExecutionError(RuntimeError):
    """
    Raised when an orchestrator step cannot be completed successfully.
    """


class StepExecutor:
    """
    Execute atomic workflow steps by sending child TransportPackets to Gate.

    This class never resolves peer nodes directly. It relies entirely on Gate
    to route the requested action.
    """

    def __init__(self, *, gate_client: GateClient, source_node: str) -> None:
        normalized_source = source_node.strip().lower()
        if not normalized_source:
            raise ValueError("source_node must not be empty")

        self._gate_client = gate_client
        self._source_node = normalized_source

    @property
    def source_node(self) -> str:
        return self._source_node

    async def execute_step(
        self,
        *,
        parent: TransportPacket,
        action: str,
        payload: dict[str, Any],
        retry_policy: RetryPolicy | None = None,
    ) -> TransportPacket:
        """
        Execute a single orchestrator step through Gate with optional retries.
        """
        policy = retry_policy or RetryPolicy()
        last_error: Exception | None = None

        for attempt in range(1, policy.max_attempts + 1):
            step_packet = build_step_packet(
                parent=parent,
                action=action,
                payload=payload,
                source_node=self._source_node,
                reply_to=self._source_node,
            )

            try:
                response = await self._gate_client.send_to_gate(step_packet)
                _ensure_success_response(response)
                return response
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if not should_retry(attempt=attempt, error=exc, policy=policy):
                    break
                delay = policy.delay_for_attempt(attempt)
                if delay > 0:
                    await asyncio.sleep(delay)

        message = f"step execution failed for action={action!r}"
        if last_error is not None:
            raise StepExecutionError(message) from last_error
        raise StepExecutionError(message)


def _ensure_success_response(packet: TransportPacket) -> None:
    packet_type = packet.header.packet_type
    if packet_type == "failure":
        raise StepExecutionError("Gate returned a failure packet")

    payload_status = str(packet.payload.get("status", "completed")).strip().lower()
    if payload_status in {"failed", "failure", "error"}:
        raise StepExecutionError("step response payload indicates failure")
# filename: tests/orchestrator/test_packet_builder.py
from __future__ import annotations

from constellation_node_sdk.orchestrator.packet_builder import build_step_packet
from constellation_node_sdk.transport.packet import create_transport_packet


def test_build_step_packet_targets_gate_and_preserves_root_lineage() -> None:
    parent = create_transport_packet(
        action="workflow.execute",
        payload={"workflow": "full_pipeline"},
        tenant="tenant-a",
        destination_node="orchestrator",
        source_node="gate",
        reply_to="gate",
    )

    child = build_step_packet(
        parent=parent,
        action="enrich",
        payload={"entity_id": "42"},
        source_node="orchestrator",
        reply_to="orchestrator",
    )

    assert child.header.packet_type == "request"
    assert child.header.action == "enrich"
    assert child.address.source_node == "orchestrator"
    assert child.address.destination_node == "gate"
    assert child.address.reply_to == "orchestrator"

    assert child.lineage.root_id == parent.lineage.root_id
    assert child.lineage.parent_id == parent.header.packet_id
    assert child.lineage.generation == parent.lineage.generation + 1

    assert child.provenance.origin_kind == "node"
    assert child.provenance.requested_action == "enrich"
    assert child.provenance.resolved_by_gate is False
    assert child.provenance.original_source_node == "orchestrator"


def test_build_step_packet_requires_non_blank_action() -> None:
    parent = create_transport_packet(
        action="workflow.execute",
        payload={},
        tenant="tenant-a",
        destination_node="orchestrator",
        source_node="gate",
        reply_to="gate",
    )

    try:
        build_step_packet(
            parent=parent,
            action="   ",
            payload={},
            source_node="orchestrator",
            reply_to="orchestrator",
        )
    except ValueError as exc:
        assert "action must not be empty" in str(exc)
    else:
        raise AssertionError("expected ValueError")
# filename: tests/orchestrator/test_merge.py
from __future__ import annotations

from constellation_node_sdk.orchestrator.merge import merge_identity, merge_payload, merge_results
from constellation_node_sdk.transport.packet import create_transport_packet


def test_merge_identity_replaces_accumulated_payload() -> None:
    current = create_transport_packet(
        action="workflow.execute",
        payload={"a": 1, "b": 2},
        tenant="tenant-a",
        destination_node="orchestrator",
        source_node="gate",
        reply_to="gate",
    )
    response = create_transport_packet(
        action="enrich",
        payload={"status": "completed", "data": {"industry": "fintech"}},
        tenant="tenant-a",
        destination_node="orchestrator",
        source_node="gate",
        reply_to="gate",
    )

    merged = merge_identity(current, response)
    assert merged == {"status": "completed", "data": {"industry": "fintech"}}


def test_merge_results_prefers_response_data_dict() -> None:
    current = create_transport_packet(
        action="workflow.execute",
        payload={"entity_id": "42", "name": "Example Corp"},
        tenant="tenant-a",
        destination_node="orchestrator",
        source_node="gate",
        reply_to="gate",
    )
    response = create_transport_packet(
        action="enrich",
        payload={"status": "completed", "data": {"industry": "manufacturing", "confidence": 0.91}},
        tenant="tenant-a",
        destination_node="orchestrator",
        source_node="gate",
        reply_to="gate",
    )

    merged = merge_results(current, response)
    assert merged == {
        "entity_id": "42",
        "name": "Example Corp",
        "industry": "manufacturing",
        "confidence": 0.91,
    }


def test_merge_payload_merges_full_response_payload() -> None:
    current = create_transport_packet(
        action="workflow.execute",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="orchestrator",
        source_node="gate",
        reply_to="gate",
    )
    response = create_transport_packet(
        action="score",
        payload={"status": "completed", "score": 88, "explanation": "high fit"},
        tenant="tenant-a",
        destination_node="orchestrator",
        source_node="gate",
        reply_to="gate",
    )

    merged = merge_payload(current, response)
    assert merged == {
        "entity_id": "42",
        "status": "completed",
        "score": 88,
        "explanation": "high fit",
    }
# filename: tests/orchestrator/test_retry.py
from __future__ import annotations

from constellation_node_sdk.orchestrator.retry import RetryPolicy, should_retry


class GateClientError(Exception):
    pass


class NonRetryableError(Exception):
    pass


def test_retry_policy_delay_is_capped() -> None:
    policy = RetryPolicy(
        max_attempts=5,
        initial_delay_seconds=0.5,
        backoff_multiplier=2.0,
        max_delay_seconds=1.25,
    )

    assert policy.delay_for_attempt(1) == 0.5
    assert policy.delay_for_attempt(2) == 1.0
    assert policy.delay_for_attempt(3) == 1.25
    assert policy.delay_for_attempt(4) == 1.25


def test_should_retry_returns_true_for_retryable_error_before_limit() -> None:
    policy = RetryPolicy(
        max_attempts=3,
        retryable_error_types=("GateClientError", "TimeoutError"),
    )

    assert should_retry(
        attempt=1,
        error=GateClientError("temporary failure"),
        policy=policy,
    ) is True


def test_should_retry_returns_false_for_non_retryable_error_or_limit() -> None:
    policy = RetryPolicy(
        max_attempts=2,
        retryable_error_types=("GateClientError",),
    )

    assert should_retry(
        attempt=1,
        error=NonRetryableError("hard failure"),
        policy=policy,
    ) is False

    assert should_retry(
        attempt=2,
        error=GateClientError("retry budget exhausted"),
        policy=policy,
    ) is False
This pass gives you:

a real orchestrator substrate

deterministic workflow state

production-leaning retry semantics

merge strategies aligned with packet-native orchestration

strict Gate-only step composition

tests for the most contract-sensitive orchestrator utilities

🚀 Your Next Prompt

Generate a 10-file pass for constellation-gate covering the strict ingress boundary: complete runnable files for src/constellation_gate/config/settings.py, schemas/registry.py, schemas/workflow.py, boundary/transport_codec.py, boundary/routing_policy.py, boundary/ingress_validator.py, plus tests/boundary/test_transport_codec.py, tests/boundary/test_routing_policy.py, tests/boundary/test_ingress_validator.py, and tests/architecture/test_gate_only_routing.py, all importing TransportPacket exclusively from constellation-node-sdk.

Reply Y to use this as your next prompt!


Y

Strategic reasoning:

This pass locks the strict ingress boundary for constellation-gate: canonical packet decode, node-origin routing policy, ingress validation, and architecture tests proving Gate-only routing. That is the highest-leverage first slice on the Gate side because it turns the SDK contract into an enforced server boundary before resolver/dispatch/workflow layers are added. It also matches the hard-cut decision: no shim, no legacy body path, TransportPacket only.

# filename: src/constellation_gate/config/settings.py
from __future__ import annotations

import os
from functools import lru_cache

from pydantic import BaseModel, ConfigDict, Field, field_validator

_ALLOWED_ENVIRONMENTS = {"local", "dev", "test", "staging", "prod"}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_tuple(name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None:
        return default
    return tuple(item.strip().lower() for item in raw.split(",") if item.strip())


class GateSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    environment: str = "local"
    local_node: str = "gate"

    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)

    require_signature: bool = False
    dev_mode: bool = False
    signing_key: str | None = None
    signing_key_id: str | None = None
    signing_algorithm: str | None = None
    verifying_keys: dict[str, str] = Field(default_factory=dict)

    allowed_actions: tuple[str, ...] = ()
    allowed_packet_types: tuple[str, ...] = ("request", "command", "delegation", "replay_request")
    required_idempotency_actions: tuple[str, ...] = ()

    allowed_clock_skew_seconds: int = Field(default=30, ge=0)
    max_packet_bytes: int = Field(default=262_144, ge=1024)
    max_hop_depth: int = Field(default=64, ge=1)
    max_delegation_depth: int = Field(default=8, ge=1)
    max_attachments: int = Field(default=32, ge=0)
    max_attachment_size_bytes: int = Field(default=10_485_760, ge=0)
    attachment_allowed_schemes: tuple[str, ...] = ()
    allow_private_attachment_hosts: bool = False

    replay_enabled: bool = True
    verify_hop_signatures: bool = False
    admin_token: str | None = None

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_ENVIRONMENTS:
            raise ValueError(f"environment must be one of {sorted(_ALLOWED_ENVIRONMENTS)}")
        return normalized

    @field_validator("local_node", "host")
    @classmethod
    def validate_required_strings(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized

    @field_validator("signing_key_id", "signing_algorithm", "admin_token")
    @classmethod
    def validate_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("optional string fields must not be blank")
        return normalized

    @field_validator("allowed_actions", "allowed_packet_types", "required_idempotency_actions", "attachment_allowed_schemes")
    @classmethod
    def validate_tuples(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip().lower() for item in value if item.strip())
        if len(set(normalized)) != len(normalized):
            raise ValueError("tuple entries must not contain duplicates")
        return normalized

    @field_validator("verifying_keys")
    @classmethod
    def validate_verifying_keys(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for key_id, key_value in value.items():
            rendered_key = key_id.strip()
            rendered_value = key_value.strip()
            if not rendered_key or not rendered_value:
                raise ValueError("verifying_keys must not contain blank keys or values")
            normalized[rendered_key] = rendered_value
        return normalized

    def resolve_verifying_key(self, key_id: str | None) -> str | bytes | None:
        if key_id is None:
            return None
        if key_id in self.verifying_keys:
            return self.verifying_keys[key_id]
        if self.signing_key_id is not None and key_id == self.signing_key_id and self.signing_key is not None:
            return self.signing_key
        return None


@lru_cache
def get_settings() -> GateSettings:
    return GateSettings(
        environment=os.getenv("L9_ENVIRONMENT", "local"),
        local_node=os.getenv("GATE_LOCAL_NODE", "gate"),
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        require_signature=_env_bool("L9_REQUIRE_SIGNATURE", False),
        dev_mode=_env_bool("L9_DEV_MODE", False),
        signing_key=os.getenv("L9_SIGNING_KEY") or os.getenv("L9_SIGNING_SECRET"),
        signing_key_id=os.getenv("L9_SIGNING_KEY_ID"),
        signing_algorithm=os.getenv("L9_SIGNING_ALGORITHM"),
        verifying_keys={},
        allowed_actions=_env_tuple("L9_ALLOWED_ACTIONS"),
        allowed_packet_types=_env_tuple("L9_ALLOWED_PACKET_TYPES", ("request", "command", "delegation", "replay_request")),
        required_idempotency_actions=_env_tuple("L9_REQUIRE_IDEMPOTENCY_FOR_ACTIONS"),
        allowed_clock_skew_seconds=int(os.getenv("L9_ALLOWED_CLOCK_SKEW_SECONDS", "30")),
        max_packet_bytes=int(os.getenv("L9_MAX_PACKET_BYTES", "262144")),
        max_hop_depth=int(os.getenv("L9_MAX_HOP_DEPTH", "64")),
        max_delegation_depth=int(os.getenv("L9_MAX_DELEGATION_DEPTH", "8")),
        max_attachments=int(os.getenv("L9_MAX_ATTACHMENTS", "32")),
        max_attachment_size_bytes=int(os.getenv("L9_MAX_ATTACHMENT_SIZE_BYTES", "10485760")),
        attachment_allowed_schemes=_env_tuple("L9_ATTACHMENT_ALLOWED_SCHEMES"),
        allow_private_attachment_hosts=_env_bool("L9_ALLOW_PRIVATE_ATTACHMENT_HOSTS", False),
        replay_enabled=_env_bool("L9_REPLAY_ENABLED", True),
        verify_hop_signatures=_env_bool("L9_VERIFY_HOP_SIGNATURES", False),
        admin_token=os.getenv("L9_GATE_ADMIN_TOKEN"),
    )
# filename: src/constellation_gate/schemas/registry.py
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator


class NodeRegistrationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    internal_url: str
    supported_actions: list[str]
    priority_class: str = "P2"
    max_concurrent: int = Field(default=50, ge=1)
    health_endpoint: str = "/v1/health"
    timeout_ms: int = Field(default=30_000, ge=1)
    metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("internal_url")
    @classmethod
    def validate_internal_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if not normalized:
            raise ValueError("internal_url must not be empty")
        if not (normalized.startswith("http://") or normalized.startswith("https://")):
            raise ValueError("internal_url must start with http:// or https://")
        return normalized

    @field_validator("supported_actions")
    @classmethod
    def validate_supported_actions(cls, value: list[str]) -> list[str]:
        normalized = [item.strip().lower() for item in value if item.strip()]
        if not normalized:
            raise ValueError("supported_actions must not be empty")
        if len(set(normalized)) != len(normalized):
            raise ValueError("supported_actions must not contain duplicates")
        return normalized

    @field_validator("priority_class")
    @classmethod
    def validate_priority_class(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in {"P0", "P1", "P2", "P3"}:
            raise ValueError("priority_class must be one of P0, P1, P2, P3")
        return normalized

    @field_validator("health_endpoint")
    @classmethod
    def validate_health_endpoint(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.startswith("/"):
            raise ValueError("health_endpoint must start with /")
        return normalized


class RegisterNodesRequest(RootModel[dict[str, NodeRegistrationInput]]):
    pass


class NodeRegistrationStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_name: str
    healthy: bool
    registered: bool = True


class RegisterNodesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registered: list[NodeRegistrationStatus]
    total_nodes: int = Field(ge=0)
# filename: src/constellation_gate/schemas/workflow.py
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WorkflowStepSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str
    timeout_ms: int | None = Field(default=None, ge=1)
    payload_transform: str = "merge_payload"
    condition: str | None = None
    target_node: str | None = None

    @field_validator("action", "payload_transform", "condition", "target_node")
    @classmethod
    def validate_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("string fields must not be blank")
        return normalized


class WorkflowSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = ""
    steps: list[WorkflowStepSchema]

    @field_validator("steps")
    @classmethod
    def validate_steps(cls, value: list[WorkflowStepSchema]) -> list[WorkflowStepSchema]:
        if not value:
            raise ValueError("workflow must contain at least one step")
        return value


class WorkflowConfigSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflows: dict[str, WorkflowSchema]
# filename: src/constellation_gate/boundary/transport_codec.py
from __future__ import annotations

from typing import Any

from constellation_node_sdk.transport.packet import TransportPacket


def decode_request_body(body: dict[str, Any]) -> TransportPacket:
    """
    Decode a canonical request body into a TransportPacket.

    Gate accepts canonical TransportPacket JSON only.
    """
    if not isinstance(body, dict):
        raise ValueError("request body must be a JSON object")
    return TransportPacket.model_validate(body)


def encode_response_body(packet: TransportPacket) -> dict[str, Any]:
    """
    Encode a canonical TransportPacket for HTTP JSON response.
    """
    return packet.model_dump_json_dict()
# filename: src/constellation_gate/boundary/routing_policy.py
from __future__ import annotations

from constellation_node_sdk.transport.packet import TransportPacket


class RoutingPolicyError(Exception):
    """Raised when a packet violates Gate routing policy."""


def validate_node_origin_policy(packet: TransportPacket, *, local_node: str, known_nodes: set[str]) -> None:
    """
    Enforce that node-originated packets re-enter Gate instead of targeting peers directly.
    """
    normalized_local = local_node.strip().lower()
    source = packet.address.source_node
    destination = packet.address.destination_node
    origin_kind = packet.provenance.origin_kind

    if origin_kind == "node":
        if source not in known_nodes:
            raise RoutingPolicyError(f"unknown node origin: {source}")
        if destination != normalized_local:
            raise RoutingPolicyError(
                f"node-originated packets must target {normalized_local!r}, got {destination!r}"
            )
        if packet.provenance.original_source_node not in {None, source}:
            raise RoutingPolicyError("node-originated packet original_source_node must match source_node")


def validate_gate_dispatch_policy(packet: TransportPacket, *, local_node: str) -> None:
    """
    Enforce that only Gate may emit direct worker-targeted dispatch packets.
    """
    normalized_local = local_node.strip().lower()

    if packet.provenance.origin_kind != "gate":
        raise RoutingPolicyError("direct worker-targeted dispatch packets must have origin_kind='gate'")

    if packet.address.source_node != normalized_local:
        raise RoutingPolicyError("Gate dispatch packet source_node must equal local Gate node")

    if packet.address.destination_node == normalized_local:
        raise RoutingPolicyError("Gate dispatch packet destination_node must not point back to Gate")

    if packet.provenance.resolved_by_gate is not True:
        raise RoutingPolicyError("Gate dispatch packet must set resolved_by_gate=true")
# filename: src/constellation_gate/boundary/ingress_validator.py
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from constellation_node_sdk.security.validation import validate_transport_packet
from constellation_node_sdk.transport.packet import TransportPacket

from .routing_policy import validate_node_origin_policy
from .transport_codec import decode_request_body


class IngressValidationError(Exception):
    """Raised when a request fails Gate ingress validation."""


class IngressValidator:
    """
    Strict Gate ingress validator for canonical TransportPacket requests.
    """

    def __init__(
        self,
        *,
        local_node: str,
        known_nodes_provider: Callable[[], set[str]] | None = None,
        allowed_actions: tuple[str, ...] = (),
        allowed_packet_types: tuple[str, ...] = ("request", "command", "delegation", "replay_request"),
        allowed_clock_skew_seconds: int = 30,
        max_packet_bytes: int = 262_144,
        max_hop_depth: int = 64,
        max_delegation_depth: int = 8,
        max_attachments: int = 32,
        max_attachment_size_bytes: int = 10_485_760,
        allowed_attachment_schemes: tuple[str, ...] = (),
        allow_private_attachment_hosts: bool = False,
        require_signature: bool = False,
        key_resolver: Callable[[str | None], str | bytes | None] | None = None,
        required_idempotency_actions: tuple[str, ...] = (),
        replay_enabled: bool = True,
        dev_mode: bool = False,
        verify_hop_signatures: bool = False,
        hop_key_resolver: Callable[[str | None], str | bytes | None] | None = None,
    ) -> None:
        self._local_node = local_node.strip().lower()
        self._known_nodes_provider = known_nodes_provider or (lambda: set())
        self._allowed_actions = allowed_actions
        self._allowed_packet_types = allowed_packet_types
        self._allowed_clock_skew_seconds = allowed_clock_skew_seconds
        self._max_packet_bytes = max_packet_bytes
        self._max_hop_depth = max_hop_depth
        self._max_delegation_depth = max_delegation_depth
        self._max_attachments = max_attachments
        self._max_attachment_size_bytes = max_attachment_size_bytes
        self._allowed_attachment_schemes = allowed_attachment_schemes
        self._allow_private_attachment_hosts = allow_private_attachment_hosts
        self._require_signature = require_signature
        self._key_resolver = key_resolver
        self._required_idempotency_actions = required_idempotency_actions
        self._replay_enabled = replay_enabled
        self._dev_mode = dev_mode
        self._verify_hop_signatures = verify_hop_signatures
        self._hop_key_resolver = hop_key_resolver

    def validate(self, body: dict[str, Any]) -> TransportPacket:
        """
        Decode and validate a strict canonical TransportPacket request.
        """
        try:
            packet = decode_request_body(body)
            validate_transport_packet(
                packet,
                key_resolver=self._key_resolver,
                require_signature=self._require_signature,
                max_packet_bytes=self._max_packet_bytes,
                max_hop_depth=self._max_hop_depth,
                max_delegation_depth=self._max_delegation_depth,
                max_attachments=self._max_attachments,
                max_attachment_size_bytes=self._max_attachment_size_bytes,
                allowed_attachment_schemes=self._allowed_attachment_schemes,
                allow_private_attachment_hosts=self._allow_private_attachment_hosts,
                allowed_clock_skew_seconds=self._allowed_clock_skew_seconds,
                local_node=self._local_node,
                allowed_actions=self._allowed_actions or None,
                allowed_packet_types=self._allowed_packet_types or None,
                required_idempotency_actions=self._required_idempotency_actions or None,
                replay_enabled=self._replay_enabled,
                dev_mode=self._dev_mode,
                verify_hop_signatures=self._verify_hop_signatures,
                hop_key_resolver=self._hop_key_resolver,
            )
            validate_node_origin_policy(
                packet,
                local_node=self._local_node,
                known_nodes=self._known_nodes_provider(),
            )
            return packet
        except Exception as exc:  # noqa: BLE001
            raise IngressValidationError(str(exc)) from exc
# filename: tests/boundary/test_transport_codec.py
from __future__ import annotations

from constellation_gate.boundary.transport_codec import decode_request_body, encode_response_body
from constellation_node_sdk.transport.packet import TransportPacket, create_transport_packet


def test_decode_request_body_round_trips_canonical_transport_packet() -> None:
    packet = create_transport_packet(
        action="enrich",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )

    decoded = decode_request_body(packet.model_dump_json_dict())

    assert isinstance(decoded, TransportPacket)
    assert decoded.header.packet_id == packet.header.packet_id
    assert decoded.security.transport_hash == packet.security.transport_hash


def test_encode_response_body_returns_json_safe_dict() -> None:
    packet = create_transport_packet(
        action="enrich",
        payload={"status": "completed"},
        tenant="tenant-a",
        destination_node="client",
        source_node="gate",
        reply_to="gate",
    )

    body = encode_response_body(packet)

    assert isinstance(body, dict)
    assert body["header"]["action"] == "enrich"
    assert body["payload"]["status"] == "completed"
# filename: tests/boundary/test_routing_policy.py
from __future__ import annotations

import pytest

from constellation_gate.boundary.routing_policy import (
    RoutingPolicyError,
    validate_gate_dispatch_policy,
    validate_node_origin_policy,
)
from constellation_node_sdk.transport.packet import create_transport_packet
from constellation_node_sdk.transport.provenance import RoutingProvenance


def test_validate_node_origin_policy_accepts_registered_node_targeting_gate() -> None:
    packet = create_transport_packet(
        action="enrich",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="orchestrator",
        reply_to="orchestrator",
        provenance=RoutingProvenance(
            origin_kind="node",
            requested_action="enrich",
            resolved_by_gate=False,
            original_source_node="orchestrator",
        ),
    )

    validate_node_origin_policy(
        packet,
        local_node="gate",
        known_nodes={"orchestrator", "enrich"},
    )


def test_validate_node_origin_policy_rejects_direct_node_to_node_target() -> None:
    packet = create_transport_packet(
        action="enrich",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="enrich",
        source_node="orchestrator",
        reply_to="orchestrator",
        provenance=RoutingProvenance(
            origin_kind="node",
            requested_action="enrich",
            resolved_by_gate=False,
            original_source_node="orchestrator",
        ),
    )

    with pytest.raises(RoutingPolicyError):
        validate_node_origin_policy(
            packet,
            local_node="gate",
            known_nodes={"orchestrator", "enrich"},
        )


def test_validate_gate_dispatch_policy_accepts_gate_authored_worker_dispatch() -> None:
    packet = create_transport_packet(
        action="enrich",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="enrich",
        source_node="gate",
        reply_to="gate",
        provenance=RoutingProvenance(
            origin_kind="gate",
            requested_action="enrich",
            resolved_by_gate=True,
            original_source_node="orchestrator",
        ),
    )

    validate_gate_dispatch_policy(packet, local_node="gate")
# filename: tests/boundary/test_ingress_validator.py
from __future__ import annotations

import pytest

from constellation_gate.boundary.ingress_validator import IngressValidationError, IngressValidator
from constellation_node_sdk.transport.packet import create_transport_packet
from constellation_node_sdk.transport.provenance import RoutingProvenance


def test_ingress_validator_accepts_canonical_client_request_to_gate() -> None:
    validator = IngressValidator(local_node="gate")

    packet = create_transport_packet(
        action="enrich",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )

    validated = validator.validate(packet.model_dump_json_dict())

    assert validated.header.action == "enrich"
    assert validated.address.destination_node == "gate"


def test_ingress_validator_rejects_non_canonical_request_body() -> None:
    validator = IngressValidator(local_node="gate")

    with pytest.raises(IngressValidationError):
        validator.validate({"action": "enrich", "payload": {"entity_id": "42"}})


def test_ingress_validator_rejects_node_to_peer_routing() -> None:
    validator = IngressValidator(
        local_node="gate",
        known_nodes_provider=lambda: {"orchestrator", "enrich"},
    )

    packet = create_transport_packet(
        action="enrich",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="enrich",
        source_node="orchestrator",
        reply_to="orchestrator",
        provenance=RoutingProvenance(
            origin_kind="node",
            requested_action="enrich",
            resolved_by_gate=False,
            original_source_node="orchestrator",
        ),
    )

    with pytest.raises(IngressValidationError):
        validator.validate(packet.model_dump_json_dict())
# filename: tests/architecture/test_gate_only_routing.py
from __future__ import annotations

import pytest

from constellation_gate.boundary.ingress_validator import IngressValidationError, IngressValidator
from constellation_gate.boundary.routing_policy import RoutingPolicyError, validate_gate_dispatch_policy
from constellation_node_sdk.transport.packet import create_transport_packet
from constellation_node_sdk.transport.provenance import RoutingProvenance


def test_architecture_rejects_direct_node_to_node_packet_at_gate_ingress() -> None:
    validator = IngressValidator(
        local_node="gate",
        known_nodes_provider=lambda: {"orchestrator", "score", "enrich"},
    )

    illegal_packet = create_transport_packet(
        action="score",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="score",
        source_node="orchestrator",
        reply_to="orchestrator",
        provenance=RoutingProvenance(
            origin_kind="node",
            requested_action="score",
            resolved_by_gate=False,
            original_source_node="orchestrator",
        ),
    )

    with pytest.raises(IngressValidationError):
        validator.validate(illegal_packet.model_dump_json_dict())


def test_architecture_allows_node_to_gate_then_gate_to_worker_split() -> None:
    validator = IngressValidator(
        local_node="gate",
        known_nodes_provider=lambda: {"orchestrator", "score", "enrich"},
    )

    node_to_gate_packet = create_transport_packet(
        action="score",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="orchestrator",
        reply_to="orchestrator",
        provenance=RoutingProvenance(
            origin_kind="node",
            requested_action="score",
            resolved_by_gate=False,
            original_source_node="orchestrator",
        ),
    )

    validated = validator.validate(node_to_gate_packet.model_dump_json_dict())
    assert validated.address.destination_node == "gate"

    gate_dispatch_packet = create_transport_packet(
        action="score",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="score",
        source_node="gate",
        reply_to="gate",
        provenance=RoutingProvenance(
            origin_kind="gate",
            requested_action="score",
            resolved_by_gate=True,
            original_source_node="orchestrator",
        ),
    )

    validate_gate_dispatch_policy(gate_dispatch_packet, local_node="gate")


def test_architecture_rejects_non_gate_origin_for_direct_worker_dispatch() -> None:
    illegal_dispatch = create_transport_packet(
        action="score",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="score",
        source_node="orchestrator",
        reply_to="orchestrator",
        provenance=RoutingProvenance(
            origin_kind="node",
            requested_action="score",
            resolved_by_gate=True,
            original_source_node="orchestrator",
        ),
    )

    with pytest.raises(RoutingPolicyError):
        validate_gate_dispatch_policy(illegal_dispatch, local_node="gate")
This pass gives you:

strict Gate settings

registry/workflow schemas

canonical transport codec

enforced routing policy

strict ingress validation

boundary and architecture tests proving the no-direct-node-to-node invariant

🚀 Your Next Prompt

Generate a 10-file pass for constellation-gate covering the routing kernel: complete runnable files for routing/node_registry.py, routing/resolver.py, routing/dispatch.py, routing/health_monitor.py, routing/priority_queue.py, plus tests/routing/test_registry.py, tests/routing/test_resolver.py, tests/routing/test_dispatch.py, tests/routing/test_health_monitor.py, and tests/routing/test_priority_queue.py, all using TransportPacket from constellation-node-sdk and preserving Gate as the sole routing authority.

Reply Y to use this as your next prompt!


Y

Strategic reasoning:

This pass is the routing kernel, which is the actual control-plane heart of Gate. The highest-leverage requirement is to keep Gate as the sole routing authority while making the kernel production-usable: deterministic registry behavior, action resolution, canonical dispatch, health tracking, and a real priority queue surface. The tests in this pass are designed to enforce those invariants directly.

# filename: src/constellation_gate/routing/node_registry.py
from __future__ import annotations

from threading import RLock
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


class NodeRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_name: str
    internal_url: str
    supported_actions: tuple[str, ...]
    priority_class: str = "P2"
    max_concurrent: int = Field(default=50, ge=1)
    health_endpoint: str = "/v1/health"
    timeout_ms: int = Field(default=30_000, ge=1)
    metadata: dict[str, str] = Field(default_factory=dict)

    healthy: bool = True
    active_requests: int = Field(default=0, ge=0)

    @field_validator("node_name")
    @classmethod
    def validate_node_name(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("node_name must not be empty")
        return normalized

    @field_validator("internal_url")
    @classmethod
    def validate_internal_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if not normalized:
            raise ValueError("internal_url must not be empty")
        if not (normalized.startswith("http://") or normalized.startswith("https://")):
            raise ValueError("internal_url must start with http:// or https://")
        return normalized

    @field_validator("supported_actions", mode="before")
    @classmethod
    def coerce_supported_actions(cls, value: Any) -> Any:
        if isinstance(value, list):
            return tuple(value)
        return value

    @field_validator("supported_actions")
    @classmethod
    def validate_supported_actions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip().lower() for item in value if item.strip())
        if not normalized:
            raise ValueError("supported_actions must not be empty")
        if len(set(normalized)) != len(normalized):
            raise ValueError("supported_actions must not contain duplicates")
        return normalized

    @field_validator("priority_class")
    @classmethod
    def validate_priority_class(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in {"P0", "P1", "P2", "P3"}:
            raise ValueError("priority_class must be one of P0, P1, P2, P3")
        return normalized

    @field_validator("health_endpoint")
    @classmethod
    def validate_health_endpoint(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.startswith("/"):
            raise ValueError("health_endpoint must start with /")
        return normalized


class NodeRegistry:
    """
    Thread-safe registry for Gate-managed worker nodes.

    Gate is the sole routing authority. All action resolution must flow through
    this registry.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, NodeRegistration] = {}
        self._lock = RLock()

    def load_from_yaml(self, path: str) -> None:
        with open(path, "r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)

        if not isinstance(raw, dict):
            raise ValueError("node registry YAML must be a mapping")

        loaded: dict[str, NodeRegistration] = {}
        for node_name, registration_payload in raw.items():
            if not isinstance(registration_payload, dict):
                raise ValueError(f"node registry entry for {node_name!r} must be a mapping")
            loaded[node_name.strip().lower()] = NodeRegistration(
                node_name=node_name,
                **registration_payload,
            )

        with self._lock:
            self._nodes = loaded

    def register_node(self, name: str, registration: NodeRegistration, *, overwrite: bool = False) -> None:
        normalized_name = name.strip().lower()
        if not normalized_name:
            raise ValueError("name must not be empty")

        with self._lock:
            if normalized_name in self._nodes and not overwrite:
                raise ValueError(f"node already registered: {normalized_name}")
            if normalized_name != registration.node_name:
                registration = registration.model_copy(update={"node_name": normalized_name})
            self._nodes[normalized_name] = registration

    def resolve_action(self, action: str) -> NodeRegistration:
        normalized_action = action.strip().lower()
        if not normalized_action:
            raise ValueError("action must not be empty")

        with self._lock:
            candidates = [
                registration
                for registration in self._nodes.values()
                if normalized_action in registration.supported_actions and registration.healthy
            ]

            if not candidates:
                raise LookupError(f"no healthy node registered for action: {normalized_action}")

            ordered = sorted(
                candidates,
                key=lambda registration: (
                    registration.active_requests,
                    registration.max_concurrent,
                    registration.node_name,
                ),
            )
            return ordered[0]

    def resolve_destination(self, node_name: str) -> NodeRegistration:
        normalized_name = node_name.strip().lower()
        if not normalized_name:
            raise ValueError("node_name must not be empty")

        with self._lock:
            if normalized_name not in self._nodes:
                raise LookupError(f"unknown destination node: {normalized_name}")
            registration = self._nodes[normalized_name]
            if not registration.healthy:
                raise LookupError(f"destination node is unhealthy: {normalized_name}")
            return registration

    def mark_healthy(self, node_name: str) -> None:
        self._set_health(node_name, healthy=True)

    def mark_unhealthy(self, node_name: str) -> None:
        self._set_health(node_name, healthy=False)

    def _set_health(self, node_name: str, *, healthy: bool) -> None:
        normalized_name = node_name.strip().lower()
        with self._lock:
            if normalized_name not in self._nodes:
                raise LookupError(f"unknown node: {normalized_name}")
            self._nodes[normalized_name] = self._nodes[normalized_name].model_copy(
                update={"healthy": healthy}
            )

    def increment_active(self, node_name: str) -> None:
        normalized_name = node_name.strip().lower()
        with self._lock:
            if normalized_name not in self._nodes:
                raise LookupError(f"unknown node: {normalized_name}")
            current = self._nodes[normalized_name]
            if current.active_requests >= current.max_concurrent:
                raise RuntimeError(f"node concurrency limit reached: {normalized_name}")
            self._nodes[normalized_name] = current.model_copy(
                update={"active_requests": current.active_requests + 1}
            )

    def decrement_active(self, node_name: str) -> None:
        normalized_name = node_name.strip().lower()
        with self._lock:
            if normalized_name not in self._nodes:
                raise LookupError(f"unknown node: {normalized_name}")
            current = self._nodes[normalized_name]
            new_active = max(0, current.active_requests - 1)
            self._nodes[normalized_name] = current.model_copy(
                update={"active_requests": new_active}
            )

    def known_nodes(self) -> set[str]:
        with self._lock:
            return set(self._nodes.keys())

    def snapshot(self) -> dict[str, NodeRegistration]:
        with self._lock:
            return dict(self._nodes)
# filename: src/constellation_gate/routing/resolver.py
from __future__ import annotations

from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry
from constellation_node_sdk.transport.packet import TransportPacket


class RouteResolver:
    """
    Resolve a canonical TransportPacket to a single target node registration.

    Gate remains the sole routing authority. Nodes express intent by action;
    Gate resolves destination by policy and registry state.
    """

    def __init__(self, registry: NodeRegistry, *, local_node: str = "gate") -> None:
        self._registry = registry
        self._local_node = local_node.strip().lower()

    def resolve(self, packet: TransportPacket) -> NodeRegistration:
        """
        Resolve packet routing target.

        Rules:
        - node-originated packets arriving at Gate target Gate itself and must be
          resolved by action
        - client-originated packets target Gate and are resolved by action
        - Gate-authored dispatch packets may target an explicit worker node
        """
        destination = packet.address.destination_node.strip().lower()

        if packet.provenance.origin_kind == "gate" and destination != self._local_node:
            return self._registry.resolve_destination(destination)

        if destination == self._local_node:
            return self._registry.resolve_action(packet.header.action)

        raise LookupError(
            f"packet destination {destination!r} is not routable by resolver for origin_kind={packet.provenance.origin_kind!r}"
        )
# filename: src/constellation_gate/routing/dispatch.py
from __future__ import annotations

import httpx

from constellation_gate.boundary.routing_policy import validate_gate_dispatch_policy
from constellation_gate.routing.node_registry import NodeRegistry
from constellation_gate.routing.resolver import RouteResolver
from constellation_node_sdk.transport.hop_trace import make_dispatch_hop, make_ingress_hop
from constellation_node_sdk.transport.packet import TransportPacket
from constellation_node_sdk.transport.provenance import RoutingProvenance


class Dispatcher:
    """
    Gate-owned internal dispatcher.

    Only Gate may derive direct worker-targeted dispatch packets.
    """

    def __init__(
        self,
        *,
        local_node: str,
        registry: NodeRegistry,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._local_node = local_node.strip().lower()
        self._registry = registry
        self._resolver = RouteResolver(registry, local_node=self._local_node)
        self._client = client

    async def dispatch(self, packet: TransportPacket) -> TransportPacket:
        """
        Resolve and dispatch a packet to a worker node via /v1/execute.

        The inbound packet is expected to have already passed ingress validation.
        """
        target = self._resolver.resolve(packet)

        ingress_observed = packet.with_hop(
            make_ingress_hop(
                packet=packet,
                node=self._local_node,
                action=packet.header.action,
                status="validated",
            )
        )

        dispatch_packet = ingress_observed.derive(
            packet_type=ingress_observed.header.packet_type,
            action=ingress_observed.header.action,
            source_node=self._local_node,
            destination_node=target.node_name,
            reply_to=self._local_node,
            payload=dict(ingress_observed.payload),
            provenance=RoutingProvenance(
                origin_kind="gate",
                requested_action=ingress_observed.header.action,
                resolved_by_gate=True,
                original_source_node=ingress_observed.address.source_node,
            ),
        ).with_hop(
            make_dispatch_hop(
                packet=ingress_observed,
                node=self._local_node,
                action=ingress_observed.header.action,
                target_node=target.node_name,
                status="delegated",
            )
        )

        validate_gate_dispatch_policy(dispatch_packet, local_node=self._local_node)

        self._registry.increment_active(target.node_name)
        try:
            response = await self._post_dispatch_packet(
                url=f"{target.internal_url}/v1/execute",
                timeout_ms=target.timeout_ms,
                packet=dispatch_packet,
            )
            return TransportPacket.model_validate(response)
        except httpx.TransportError as exc:
            self._registry.mark_unhealthy(target.node_name)
            raise RuntimeError(f"dispatch transport error to {target.node_name!r}") from exc
        finally:
            self._registry.decrement_active(target.node_name)

    async def _post_dispatch_packet(
        self,
        *,
        url: str,
        timeout_ms: int,
        packet: TransportPacket,
    ) -> dict:
        if self._client is not None:
            response = await self._client.post(
                url,
                json=packet.model_dump_json_dict(),
                headers={"Content-Type": "application/json"},
                timeout=timeout_ms / 1000,
            )
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("dispatch response body must be a JSON object")
            return body

        async with httpx.AsyncClient(timeout=timeout_ms / 1000) as client:
            response = await client.post(
                url,
                json=packet.model_dump_json_dict(),
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("dispatch response body must be a JSON object")
            return body
# filename: src/constellation_gate/routing/health_monitor.py
from __future__ import annotations

import asyncio

import httpx

from constellation_gate.routing.node_registry import NodeRegistry


class HealthMonitor:
    """
    Periodically probes registered nodes and updates registry health state.
    """

    def __init__(
        self,
        registry: NodeRegistry,
        *,
        interval_seconds: float = 15.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be > 0")

        self._registry = registry
        self._interval_seconds = interval_seconds
        self._client = client
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            await self._task
            self._task = None

    async def probe_once(self) -> None:
        snapshot = self._registry.snapshot()
        for node_name, registration in snapshot.items():
            healthy = await self._probe_node(
                url=f"{registration.internal_url}{registration.health_endpoint}"
            )
            if healthy:
                self._registry.mark_healthy(node_name)
            else:
                self._registry.mark_unhealthy(node_name)

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            await self.probe_once()
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval_seconds)
            except TimeoutError:
                continue

    async def _probe_node(self, *, url: str) -> bool:
        try:
            if self._client is not None:
                response = await self._client.get(url, timeout=5.0)
                return response.status_code == 200

            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(url)
                return response.status_code == 200
        except httpx.TransportError:
            return False
# filename: src/constellation_gate/routing/priority_queue.py
from __future__ import annotations

import asyncio
from itertools import count
from typing import Any

from constellation_node_sdk.transport.packet import TransportPacket


class PriorityPacketQueue:
    """
    Async priority queue for TransportPackets.

    Lower numeric priority is higher urgency:
    - 0 => P0
    - 1 => P1
    - 2 => P2
    - 3 => P3
    """

    def __init__(self) -> None:
        self._queue: asyncio.PriorityQueue[tuple[int, int, TransportPacket]] = asyncio.PriorityQueue()
        self._sequence = count()

    async def put(self, packet: TransportPacket) -> None:
        await self._queue.put((packet.header.priority, next(self._sequence), packet))

    async def get(self) -> TransportPacket:
        _priority, _sequence, packet = await self._queue.get()
        return packet

    def qsize(self) -> int:
        return self._queue.qsize()

    def empty(self) -> bool:
        return self._queue.empty()

    async def drain(self) -> tuple[TransportPacket, ...]:
        items: list[TransportPacket] = []
        while not self._queue.empty():
            items.append(await self.get())
        return tuple(items)

    def task_done(self) -> None:
        self._queue.task_done()

    async def join(self) -> None:
        await self._queue.join()

    def debug_snapshot(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            {
                "priority": priority,
                "sequence": sequence,
                "packet_id": str(packet.header.packet_id),
                "action": packet.header.action,
            }
            for priority, sequence, packet in list(self._queue._queue)  # noqa: SLF001
        )
# filename: tests/routing/test_registry.py
from __future__ import annotations

from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry


def test_registry_resolves_least_loaded_healthy_node_for_action() -> None:
    registry = NodeRegistry()
    registry.register_node(
        "enrich-a",
        NodeRegistration(
            node_name="enrich-a",
            internal_url="http://enrich-a:8000",
            supported_actions=("enrich",),
            active_requests=3,
        ),
    )
    registry.register_node(
        "enrich-b",
        NodeRegistration(
            node_name="enrich-b",
            internal_url="http://enrich-b:8000",
            supported_actions=("enrich",),
            active_requests=1,
        ),
    )

    resolved = registry.resolve_action("enrich")
    assert resolved.node_name == "enrich-b"


def test_registry_resolve_destination_rejects_unhealthy_node() -> None:
    registry = NodeRegistry()
    registry.register_node(
        "score",
        NodeRegistration(
            node_name="score",
            internal_url="http://score:8000",
            supported_actions=("score",),
            healthy=False,
        ),
    )

    try:
        registry.resolve_destination("score")
    except LookupError as exc:
        assert "unhealthy" in str(exc)
    else:
        raise AssertionError("expected LookupError")


def test_registry_increment_and_decrement_active_track_concurrency() -> None:
    registry = NodeRegistry()
    registry.register_node(
        "score",
        NodeRegistration(
            node_name="score",
            internal_url="http://score:8000",
            supported_actions=("score",),
            max_concurrent=2,
            active_requests=0,
        ),
    )

    registry.increment_active("score")
    registry.increment_active("score")
    snapshot = registry.snapshot()
    assert snapshot["score"].active_requests == 2

    registry.decrement_active("score")
    snapshot = registry.snapshot()
    assert snapshot["score"].active_requests == 1
# filename: tests/routing/test_resolver.py
from __future__ import annotations

from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry
from constellation_gate.routing.resolver import RouteResolver
from constellation_node_sdk.transport.packet import create_transport_packet
from constellation_node_sdk.transport.provenance import RoutingProvenance


def _build_registry() -> NodeRegistry:
    registry = NodeRegistry()
    registry.register_node(
        "enrich",
        NodeRegistration(
            node_name="enrich",
            internal_url="http://enrich:8000",
            supported_actions=("enrich",),
        ),
    )
    registry.register_node(
        "score",
        NodeRegistration(
            node_name="score",
            internal_url="http://score:8000",
            supported_actions=("score",),
        ),
    )
    return registry


def test_resolver_resolves_gate_bound_packet_by_action() -> None:
    resolver = RouteResolver(_build_registry(), local_node="gate")

    packet = create_transport_packet(
        action="enrich",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )

    resolved = resolver.resolve(packet)
    assert resolved.node_name == "enrich"


def test_resolver_resolves_gate_authored_dispatch_by_destination() -> None:
    resolver = RouteResolver(_build_registry(), local_node="gate")

    packet = create_transport_packet(
        action="score",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="score",
        source_node="gate",
        reply_to="gate",
        provenance=RoutingProvenance(
            origin_kind="gate",
            requested_action="score",
            resolved_by_gate=True,
            original_source_node="orchestrator",
        ),
    )

    resolved = resolver.resolve(packet)
    assert resolved.node_name == "score"
# filename: tests/routing/test_dispatch.py
from __future__ import annotations

import httpx

from constellation_gate.routing.dispatch import Dispatcher
from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry
from constellation_node_sdk.transport.packet import TransportPacket, create_transport_packet
from constellation_node_sdk.transport.provenance import RoutingProvenance


class FakeAsyncClient:
    def __init__(self, response_body: dict) -> None:
        self._response_body = response_body
        self.calls: list[dict] = []

    async def post(self, url: str, json: dict, headers: dict, timeout: float) -> httpx.Response:
        self.calls.append(
            {
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": timeout,
            }
        )
        request = httpx.Request("POST", url)
        return httpx.Response(status_code=200, json=self._response_body, request=request)


def test_dispatch_creates_gate_authored_worker_dispatch_and_posts_to_worker() -> None:
    registry = NodeRegistry()
    registry.register_node(
        "score",
        NodeRegistration(
            node_name="score",
            internal_url="http://score:8000",
            supported_actions=("score",),
            timeout_ms=15_000,
        ),
    )

    response_packet = create_transport_packet(
        action="score",
        payload={"status": "completed", "score": 91},
        tenant="tenant-a",
        destination_node="gate",
        source_node="score",
        reply_to="gate",
    )
    fake_client = FakeAsyncClient(response_packet.model_dump_json_dict())
    dispatcher = Dispatcher(local_node="gate", registry=registry, client=fake_client)

    inbound_packet = create_transport_packet(
        action="score",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="orchestrator",
        reply_to="orchestrator",
        provenance=RoutingProvenance(
            origin_kind="node",
            requested_action="score",
            resolved_by_gate=False,
            original_source_node="orchestrator",
        ),
    )

    result = __import__("asyncio").run(dispatcher.dispatch(inbound_packet))

    assert isinstance(result, TransportPacket)
    assert result.payload["score"] == 91
    assert len(fake_client.calls) == 1
    call = fake_client.calls[0]
    assert call["url"] == "http://score:8000/v1/execute"

    posted_packet = TransportPacket.model_validate(call["json"])
    assert posted_packet.address.source_node == "gate"
    assert posted_packet.address.destination_node == "score"
    assert posted_packet.provenance.origin_kind == "gate"
    assert posted_packet.provenance.resolved_by_gate is True
# filename: tests/routing/test_health_monitor.py
from __future__ import annotations

import httpx

from constellation_gate.routing.health_monitor import HealthMonitor
from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry


class FakeHealthClient:
    def __init__(self, responses: dict[str, int]) -> None:
        self._responses = responses

    async def get(self, url: str, timeout: float) -> httpx.Response:
        status_code = self._responses[url]
        request = httpx.Request("GET", url)
        return httpx.Response(status_code=status_code, request=request)


def test_health_monitor_marks_nodes_healthy_and_unhealthy() -> None:
    registry = NodeRegistry()
    registry.register_node(
        "enrich",
        NodeRegistration(
            node_name="enrich",
            internal_url="http://enrich:8000",
            supported_actions=("enrich",),
            health_endpoint="/v1/health",
        ),
    )
    registry.register_node(
        "score",
        NodeRegistration(
            node_name="score",
            internal_url="http://score:8000",
            supported_actions=("score",),
            health_endpoint="/v1/health",
        ),
    )

    client = FakeHealthClient(
        {
            "http://enrich:8000/v1/health": 200,
            "http://score:8000/v1/health": 503,
        }
    )
    monitor = HealthMonitor(registry, interval_seconds=60.0, client=client)

    __import__("asyncio").run(monitor.probe_once())

    snapshot = registry.snapshot()
    assert snapshot["enrich"].healthy is True
    assert snapshot["score"].healthy is False
# filename: tests/routing/test_priority_queue.py
from __future__ import annotations

import asyncio

from constellation_gate.routing.priority_queue import PriorityPacketQueue
from constellation_node_sdk.transport.packet import create_transport_packet


def test_priority_queue_returns_lower_numeric_priority_first() -> None:
    async def run() -> None:
        queue = PriorityPacketQueue()

        p2_packet = create_transport_packet(
            action="enrich",
            payload={"id": "a"},
            tenant="tenant-a",
            destination_node="gate",
            source_node="client",
            reply_to="client",
            priority=2,
        )
        p0_packet = create_transport_packet(
            action="score",
            payload={"id": "b"},
            tenant="tenant-a",
            destination_node="gate",
            source_node="client",
            reply_to="client",
            priority=0,
        )

        await queue.put(p2_packet)
        await queue.put(p0_packet)

        first = await queue.get()
        second = await queue.get()

        assert first.header.priority == 0
        assert second.header.priority == 2

    asyncio.run(run())


def test_priority_queue_preserves_fifo_within_same_priority() -> None:
    async def run() -> None:
        queue = PriorityPacketQueue()

        first_packet = create_transport_packet(
            action="enrich",
            payload={"id": "first"},
            tenant="tenant-a",
            destination_node="gate",
            source_node="client",
            reply_to="client",
            priority=1,
        )
        second_packet = create_transport_packet(
            action="enrich",
            payload={"id": "second"},
            tenant="tenant-a",
            destination_node="gate",
            source_node="client",
            reply_to="client",
            priority=1,
        )

        await queue.put(first_packet)
        await queue.put(second_packet)

        first = await queue.get()
        second = await queue.get()

        assert first.payload["id"] == "first"
        assert second.payload["id"] == "second"

    asyncio.run(run())
This pass gives you:

thread-safe node registry with health and concurrency tracking

resolver that preserves Gate’s sole routing authority

dispatcher that derives Gate-authored worker dispatch packets

health monitor for periodic worker probing

async priority queue for packet scheduling

routing tests that enforce the core control-plane semantics

🚀 Your Next Prompt

Generate a 10-file pass for constellation-gate covering workflow and execution services: complete runnable files for orchestration/workflow_models.py, orchestration/condition_eval.py, orchestration/workflow_engine.py, services/execute_service.py, services/registry_query_service.py, plus tests/orchestration/test_workflow_models.py, tests/orchestration/test_condition_eval.py, tests/orchestration/test_workflow_engine.py, tests/services/test_execute_service.py, and tests/services/test_registry_query_service.py, all packet-native and aligned with Gate-only routing.

Reply Y to use this as your next prompt!


Y


Thought for 32s
Strategic reasoning:

This pass turns the Gate kernel into an actual packet-native execution surface: workflow definitions, safe conditional flow, sequential workflow execution through the dispatcher, and the first service layer that chooses between direct dispatch and workflow execution. That is the highest-leverage next slice because it makes Gate do real work while preserving the architectural law that all routing still flows through Gate-owned authority.

# filename: src/constellation_gate/orchestration/workflow_models.py
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


_ALLOWED_MERGE_STRATEGIES = {"identity", "merge_payload", "merge_results"}


class WorkflowStep(BaseModel):
    """
    Canonical Gate workflow step definition.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    action: str
    timeout_ms: int | None = Field(default=None, ge=1)
    merge_strategy: str = "merge_payload"
    condition: str | None = None

    @field_validator("name", "action", "condition")
    @classmethod
    def validate_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("string fields must not be blank")
        return normalized

    @field_validator("merge_strategy")
    @classmethod
    def validate_merge_strategy(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_MERGE_STRATEGIES:
            raise ValueError(f"merge_strategy must be one of {sorted(_ALLOWED_MERGE_STRATEGIES)}")
        return normalized


class WorkflowDefinition(BaseModel):
    """
    Sequential workflow definition resolved by Gate for composite actions.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    steps: tuple[WorkflowStep, ...]

    @field_validator("name", "description")
    @classmethod
    def validate_strings(cls, value: str) -> str:
        normalized = value.strip()
        if value == "":
            return value
        if not normalized and value != "":
            raise ValueError("string fields must not be blank")
        return normalized

    @field_validator("steps", mode="before")
    @classmethod
    def coerce_steps(cls, value: tuple[WorkflowStep, ...] | list[WorkflowStep]) -> tuple[WorkflowStep, ...]:
        if isinstance(value, list):
            return tuple(value)
        return value

    @field_validator("steps")
    @classmethod
    def validate_steps(cls, value: tuple[WorkflowStep, ...]) -> tuple[WorkflowStep, ...]:
        if not value:
            raise ValueError("workflow must contain at least one step")
        names = [step.name.strip().lower() for step in value]
        if len(set(names)) != len(names):
            raise ValueError("workflow step names must be unique")
        return value
# filename: src/constellation_gate/orchestration/condition_eval.py
from __future__ import annotations

import ast
from typing import Any


_ALLOWED_COMPARE_OPS = (
    ast.Eq,
    ast.NotEq,
    ast.Gt,
    ast.GtE,
    ast.Lt,
    ast.LtE,
    ast.In,
    ast.NotIn,
)
_ALLOWED_BOOL_OPS = (ast.And, ast.Or)
_ALLOWED_UNARY_OPS = (ast.Not,)
_ALLOWED_BIN_OPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod)


class SafeConditionEvaluator:
    """
    Safe boolean expression evaluator for workflow conditions.

    Available names:
    - payload
    - response
    - accumulated
    - action
    """

    def evaluate(
        self,
        expression: str,
        *,
        payload: dict[str, Any],
        response: dict[str, Any] | None,
        action: str,
        accumulated: dict[str, Any],
    ) -> bool:
        parsed = ast.parse(expression, mode="eval")
        return bool(
            self._eval(
                parsed.body,
                context={
                    "payload": payload,
                    "response": response,
                    "action": action,
                    "accumulated": accumulated,
                },
            )
        )

    def _eval(self, node: ast.AST, *, context: dict[str, Any]) -> Any:
        if isinstance(node, ast.Constant):
            return node.value

        if isinstance(node, ast.Name):
            if node.id not in context:
                raise ValueError(f"unknown name in condition: {node.id}")
            return context[node.id]

        if isinstance(node, ast.Expression):
            return self._eval(node.body, context=context)

        if isinstance(node, ast.BoolOp):
            if not isinstance(node.op, _ALLOWED_BOOL_OPS):
                raise ValueError("unsupported boolean operator")
            values = [bool(self._eval(value, context=context)) for value in node.values]
            if isinstance(node.op, ast.And):
                return all(values)
            return any(values)

        if isinstance(node, ast.UnaryOp):
            if not isinstance(node.op, _ALLOWED_UNARY_OPS):
                raise ValueError("unsupported unary operator")
            return not bool(self._eval(node.operand, context=context))

        if isinstance(node, ast.Compare):
            left = self._eval(node.left, context=context)
            result = True
            for op, comparator in zip(node.ops, node.comparators, strict=True):
                if not isinstance(op, _ALLOWED_COMPARE_OPS):
                    raise ValueError("unsupported comparison operator")
                right = self._eval(comparator, context=context)
                result = result and self._apply_compare(op, left, right)
                left = right
            return result

        if isinstance(node, ast.Subscript):
            value = self._eval(node.value, context=context)
            key = self._eval(node.slice, context=context)
            return value[key]

        if isinstance(node, ast.BinOp):
            if not isinstance(node.op, _ALLOWED_BIN_OPS):
                raise ValueError("unsupported binary operator")
            left = self._eval(node.left, context=context)
            right = self._eval(node.right, context=context)
            return self._apply_binop(node.op, left, right)

        if isinstance(node, ast.List):
            return [self._eval(elt, context=context) for elt in node.elts]

        if isinstance(node, ast.Tuple):
            return tuple(self._eval(elt, context=context) for elt in node.elts)

        if isinstance(node, ast.Dict):
            return {
                self._eval(key, context=context): self._eval(value, context=context)
                for key, value in zip(node.keys, node.values, strict=True)
            }

        raise ValueError(f"unsupported condition syntax: {type(node).__name__}")

    @staticmethod
    def _apply_compare(op: ast.AST, left: Any, right: Any) -> bool:
        if isinstance(op, ast.Eq):
            return left == right
        if isinstance(op, ast.NotEq):
            return left != right
        if isinstance(op, ast.Gt):
            return left > right
        if isinstance(op, ast.GtE):
            return left >= right
        if isinstance(op, ast.Lt):
            return left < right
        if isinstance(op, ast.LtE):
            return left <= right
        if isinstance(op, ast.In):
            return left in right
        if isinstance(op, ast.NotIn):
            return left not in right
        raise ValueError("unsupported comparison operator")

    @staticmethod
    def _apply_binop(op: ast.AST, left: Any, right: Any) -> Any:
        if isinstance(op, ast.Add):
            return left + right
        if isinstance(op, ast.Sub):
            return left - right
        if isinstance(op, ast.Mult):
            return left * right
        if isinstance(op, ast.Div):
            return left / right
        if isinstance(op, ast.Mod):
            return left % right
        raise ValueError("unsupported binary operator")
# filename: src/constellation_gate/orchestration/workflow_engine.py
from __future__ import annotations

from typing import Any

from constellation_gate.orchestration.condition_eval import SafeConditionEvaluator
from constellation_gate.orchestration.workflow_models import WorkflowDefinition, WorkflowStep
from constellation_gate.routing.dispatch import Dispatcher
from constellation_node_sdk.transport.packet import TransportPacket
from constellation_node_sdk.transport.provenance import RoutingProvenance


class WorkflowEngine:
    """
    Packet-native sequential workflow engine executed inside Gate.

    Gate remains the routing authority. Each workflow step is emitted as a child
    packet back through Gate-owned dispatch.
    """

    def __init__(
        self,
        definitions: dict[str, WorkflowDefinition],
        dispatcher: Dispatcher,
        *,
        local_node: str = "gate",
        condition_evaluator: SafeConditionEvaluator | None = None,
    ) -> None:
        self._definitions = {name.strip().lower(): definition for name, definition in definitions.items()}
        self._dispatcher = dispatcher
        self._local_node = local_node.strip().lower()
        self._condition_evaluator = condition_evaluator or SafeConditionEvaluator()

    def has_workflow(self, name: str) -> bool:
        return name.strip().lower() in self._definitions

    async def execute(self, packet: TransportPacket) -> TransportPacket:
        workflow_name = packet.header.action.strip().lower()
        if workflow_name not in self._definitions:
            raise LookupError(f"no workflow defined for action: {workflow_name}")

        definition = self._definitions[workflow_name]
        current_payload: dict[str, Any] = dict(packet.payload)
        latest_response_payload: dict[str, Any] | None = None
        current_packet = packet

        for step in definition.steps:
            if not self._should_execute_step(
                step,
                payload=current_payload,
                response=latest_response_payload,
                accumulated=current_payload,
            ):
                continue

            step_packet = current_packet.derive(
                packet_type="request",
                action=step.action,
                source_node=self._local_node,
                destination_node=self._local_node,
                reply_to=self._local_node,
                payload=dict(current_payload),
                provenance=RoutingProvenance(
                    origin_kind="gate",
                    requested_action=step.action,
                    resolved_by_gate=False,
                    original_source_node=packet.address.source_node,
                ),
                timeout_ms=step.timeout_ms if step.timeout_ms is not None else current_packet.header.timeout_ms,
            )

            step_response = await self._dispatcher.dispatch(step_packet)
            latest_response_payload = dict(step_response.payload)
            current_payload = self._merge_payload(
                step=step,
                current=current_payload,
                response=latest_response_payload,
            )
            current_packet = step_response

        return packet.derive(
            packet_type="response",
            source_node=self._local_node,
            destination_node=packet.address.reply_to,
            reply_to=self._local_node,
            payload=current_payload,
            provenance=RoutingProvenance(
                origin_kind="gate",
                requested_action=workflow_name,
                resolved_by_gate=True,
                original_source_node=packet.address.source_node,
            ),
        )

    def _should_execute_step(
        self,
        step: WorkflowStep,
        *,
        payload: dict[str, Any],
        response: dict[str, Any] | None,
        accumulated: dict[str, Any],
    ) -> bool:
        if step.condition is None:
            return True
        return self._condition_evaluator.evaluate(
            step.condition,
            payload=payload,
            response=response,
            action=step.action,
            accumulated=accumulated,
        )

    @staticmethod
    def _merge_payload(
        *,
        step: WorkflowStep,
        current: dict[str, Any],
        response: dict[str, Any],
    ) -> dict[str, Any]:
        if step.merge_strategy == "identity":
            return dict(response)

        if step.merge_strategy == "merge_results":
            merged = dict(current)
            response_data = response.get("data")
            if isinstance(response_data, dict):
                merged.update(response_data)
                return merged
            merged.update(response)
            return merged

        merged = dict(current)
        merged.update(response)
        return merged
# filename: src/constellation_gate/services/execute_service.py
from __future__ import annotations

from constellation_gate.orchestration.workflow_engine import WorkflowEngine
from constellation_gate.routing.dispatch import Dispatcher
from constellation_gate.routing.node_registry import NodeRegistry
from constellation_node_sdk.transport.packet import TransportPacket


class ExecuteService:
    """
    Top-level Gate execution service.

    Responsibilities:
    - strict ingress validation
    - choose workflow execution or direct dispatch
    - return canonical TransportPacket response
    """

    def __init__(
        self,
        *,
        local_node: str,
        ingress_validator: object,
        dispatcher: Dispatcher,
        workflow_engine: WorkflowEngine,
        registry: NodeRegistry,
    ) -> None:
        self._local_node = local_node.strip().lower()
        self._ingress_validator = ingress_validator
        self._dispatcher = dispatcher
        self._workflow_engine = workflow_engine
        self._registry = registry

    async def execute(self, body: dict) -> TransportPacket:
        packet = self._validate(body)
        if self._workflow_engine.has_workflow(packet.header.action):
            return await self._workflow_engine.execute(packet)
        return await self._dispatcher.dispatch(packet)

    def _validate(self, body: dict) -> TransportPacket:
        validator = self._ingress_validator
        if not hasattr(validator, "validate"):
            raise TypeError("ingress_validator must expose validate(body) -> TransportPacket")
        packet = validator.validate(body)
        if not isinstance(packet, TransportPacket):
            raise TypeError("ingress_validator returned non-TransportPacket result")
        return packet
# filename: src/constellation_gate/services/registry_query_service.py
from __future__ import annotations

from constellation_gate.routing.node_registry import NodeRegistry


class RegistryQueryService:
    """
    Read-only registry inspection service for admin and health endpoints.
    """

    def __init__(self, registry: NodeRegistry) -> None:
        self._registry = registry

    def snapshot(self) -> dict[str, dict]:
        registrations = self._registry.snapshot()
        return {
            node_name: registration.model_dump(mode="json")
            for node_name, registration in registrations.items()
        }
# filename: tests/orchestration/test_workflow_models.py
from __future__ import annotations

import pytest

from constellation_gate.orchestration.workflow_models import WorkflowDefinition, WorkflowStep


def test_workflow_definition_requires_unique_step_names() -> None:
    with pytest.raises(ValueError):
        WorkflowDefinition(
            name="full_pipeline",
            steps=(
                WorkflowStep(name="enrich", action="enrich"),
                WorkflowStep(name="enrich", action="score"),
            ),
        )


def test_workflow_step_validates_merge_strategy() -> None:
    with pytest.raises(ValueError):
        WorkflowStep(
            name="score",
            action="score",
            merge_strategy="unknown",
        )


def test_workflow_definition_accepts_valid_steps() -> None:
    definition = WorkflowDefinition(
        name="full_pipeline",
        description="Composite enrichment + scoring",
        steps=(
            WorkflowStep(name="enrich", action="enrich"),
            WorkflowStep(name="score", action="score", merge_strategy="merge_results"),
        ),
    )

    assert definition.name == "full_pipeline"
    assert len(definition.steps) == 2
    assert definition.steps[1].merge_strategy == "merge_results"
# filename: tests/orchestration/test_condition_eval.py
from __future__ import annotations

import pytest

from constellation_gate.orchestration.condition_eval import SafeConditionEvaluator


def test_condition_eval_supports_boolean_and_subscript_access() -> None:
    evaluator = SafeConditionEvaluator()

    result = evaluator.evaluate(
        "payload['score'] >= 70 and accumulated['enabled'] == True",
        payload={"score": 88},
        response=None,
        action="score",
        accumulated={"enabled": True},
    )

    assert result is True


def test_condition_eval_supports_response_and_membership() -> None:
    evaluator = SafeConditionEvaluator()

    result = evaluator.evaluate(
        "'completed' in response['status']",
        payload={},
        response={"status": "completed"},
        action="score",
        accumulated={},
    )

    assert result is True


def test_condition_eval_rejects_calls() -> None:
    evaluator = SafeConditionEvaluator()

    with pytest.raises(ValueError):
        evaluator.evaluate(
            "len(payload) > 0",
            payload={"x": 1},
            response=None,
            action="score",
            accumulated={},
        )
# filename: tests/orchestration/test_workflow_engine.py
from __future__ import annotations

import pytest

from constellation_gate.orchestration.workflow_engine import WorkflowEngine
from constellation_gate.orchestration.workflow_models import WorkflowDefinition, WorkflowStep
from constellation_node_sdk.transport.packet import TransportPacket, create_transport_packet


class FakeDispatcher:
    def __init__(self) -> None:
        self.calls: list[TransportPacket] = []

    async def dispatch(self, packet: TransportPacket) -> TransportPacket:
        self.calls.append(packet)
        if packet.header.action == "enrich":
            return packet.derive(
                packet_type="response",
                source_node="enrich",
                destination_node="gate",
                reply_to="enrich",
                payload={"status": "completed", "data": {"industry": "fintech"}},
            )
        if packet.header.action == "score":
            return packet.derive(
                packet_type="response",
                source_node="score",
                destination_node="gate",
                reply_to="score",
                payload={"status": "completed", "score": 91},
            )
        raise AssertionError(f"unexpected action: {packet.header.action}")


@pytest.mark.asyncio
async def test_workflow_engine_executes_steps_sequentially_and_merges_payload() -> None:
    dispatcher = FakeDispatcher()
    engine = WorkflowEngine(
        definitions={
            "full_pipeline": WorkflowDefinition(
                name="full_pipeline",
                steps=(
                    WorkflowStep(name="enrich", action="enrich", merge_strategy="merge_results"),
                    WorkflowStep(name="score", action="score", merge_strategy="merge_payload"),
                ),
            )
        },
        dispatcher=dispatcher,
        local_node="gate",
    )

    request = create_transport_packet(
        action="full_pipeline",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )

    response = await engine.execute(request)

    assert response.header.packet_type == "response"
    assert response.address.source_node == "gate"
    assert response.address.destination_node == "client"
    assert response.payload["entity_id"] == "42"
    assert response.payload["industry"] == "fintech"
    assert response.payload["score"] == 91
    assert len(dispatcher.calls) == 2
    assert dispatcher.calls[0].address.destination_node == "gate"
    assert dispatcher.calls[1].address.destination_node == "gate"


@pytest.mark.asyncio
async def test_workflow_engine_skips_conditional_step_when_false() -> None:
    dispatcher = FakeDispatcher()
    engine = WorkflowEngine(
        definitions={
            "conditional_pipeline": WorkflowDefinition(
                name="conditional_pipeline",
                steps=(
                    WorkflowStep(name="enrich", action="enrich", merge_strategy="merge_results"),
                    WorkflowStep(
                        name="score",
                        action="score",
                        merge_strategy="merge_payload",
                        condition="payload['run_score'] == True",
                    ),
                ),
            )
        },
        dispatcher=dispatcher,
        local_node="gate",
    )

    request = create_transport_packet(
        action="conditional_pipeline",
        payload={"entity_id": "42", "run_score": False},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )

    response = await engine.execute(request)

    assert response.payload["industry"] == "fintech"
    assert "score" not in response.payload
    assert len(dispatcher.calls) == 1
# filename: tests/services/test_execute_service.py
from __future__ import annotations

import pytest

from constellation_gate.services.execute_service import ExecuteService
from constellation_node_sdk.transport.packet import TransportPacket, create_transport_packet


class FakeIngressValidator:
    def __init__(self, packet: TransportPacket) -> None:
        self._packet = packet

    def validate(self, body: dict) -> TransportPacket:
        assert body == self._packet.model_dump_json_dict()
        return self._packet


class FakeDispatcher:
    def __init__(self, response_packet: TransportPacket) -> None:
        self.response_packet = response_packet
        self.calls: list[TransportPacket] = []

    async def dispatch(self, packet: TransportPacket) -> TransportPacket:
        self.calls.append(packet)
        return self.response_packet


class FakeWorkflowEngine:
    def __init__(self, *, has_workflow: bool, response_packet: TransportPacket) -> None:
        self._has_workflow = has_workflow
        self._response_packet = response_packet
        self.calls: list[TransportPacket] = []

    def has_workflow(self, name: str) -> bool:
        return self._has_workflow

    async def execute(self, packet: TransportPacket) -> TransportPacket:
        self.calls.append(packet)
        return self._response_packet


class FakeRegistry:
    pass


@pytest.mark.asyncio
async def test_execute_service_dispatches_atomic_request_when_no_workflow() -> None:
    request_packet = create_transport_packet(
        action="score",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )
    response_packet = request_packet.derive(
        packet_type="response",
        source_node="gate",
        destination_node="client",
        reply_to="gate",
        payload={"status": "completed", "score": 90},
    )

    dispatcher = FakeDispatcher(response_packet=response_packet)
    workflow_engine = FakeWorkflowEngine(has_workflow=False, response_packet=response_packet)
    service = ExecuteService(
        local_node="gate",
        ingress_validator=FakeIngressValidator(request_packet),
        dispatcher=dispatcher,
        workflow_engine=workflow_engine,
        registry=FakeRegistry(),
    )

    result = await service.execute(request_packet.model_dump_json_dict())

    assert result.payload["score"] == 90
    assert len(dispatcher.calls) == 1
    assert len(workflow_engine.calls) == 0


@pytest.mark.asyncio
async def test_execute_service_uses_workflow_engine_for_composite_action() -> None:
    request_packet = create_transport_packet(
        action="full_pipeline",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )
    response_packet = request_packet.derive(
        packet_type="response",
        source_node="gate",
        destination_node="client",
        reply_to="gate",
        payload={"status": "completed", "score": 93},
    )

    dispatcher = FakeDispatcher(response_packet=response_packet)
    workflow_engine = FakeWorkflowEngine(has_workflow=True, response_packet=response_packet)
    service = ExecuteService(
        local_node="gate",
        ingress_validator=FakeIngressValidator(request_packet),
        dispatcher=dispatcher,
        workflow_engine=workflow_engine,
        registry=FakeRegistry(),
    )

    result = await service.execute(request_packet.model_dump_json_dict())

    assert result.payload["score"] == 93
    assert len(dispatcher.calls) == 0
    assert len(workflow_engine.calls) == 1
# filename: tests/services/test_registry_query_service.py
from __future__ import annotations

from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry
from constellation_gate.services.registry_query_service import RegistryQueryService


def test_registry_query_service_returns_json_safe_snapshot() -> None:
    registry = NodeRegistry()
    registry.register_node(
        "enrich",
        NodeRegistration(
            node_name="enrich",
            internal_url="http://enrich:8000",
            supported_actions=("enrich",),
            priority_class="P2",
            max_concurrent=25,
        ),
    )

    service = RegistryQueryService(registry)
    snapshot = service.snapshot()

    assert "enrich" in snapshot
    assert snapshot["enrich"]["node_name"] == "enrich"
    assert snapshot["enrich"]["internal_url"] == "http://enrich:8000"
    assert snapshot["enrich"]["supported_actions"] == ["enrich"]
    assert snapshot["enrich"]["healthy"] is True
One fix note: in tests/orchestration/test_workflow_engine.py, the line asserting score should be:

assert response.payload["score"] == 91
with no trailing quote.

🚀 Your Next Prompt

Generate a 10-file pass for constellation-gate covering the admin/API surface: complete runnable files for services/admin_registration_service.py, services/workflow_service.py, api/dependencies.py, api/errors.py, api/main.py, plus tests/services/test_admin_registration_service.py, tests/services/test_workflow_service.py, tests/api/test_execute_endpoint.py, tests/api/test_admin_register_endpoint.py, and tests/api/test_registry_endpoint.py, fully packet-native and wired to the current Gate kernel.

Reply Y to use this as your next prompt!


Y

Strategic reasoning:

This pass closes the first runnable Gate slice: admin registration, workflow service, API dependency wiring, API error handling, and the FastAPI surface with tests. That is the highest-leverage next move because it turns the kernel you already built into an executable service boundary while preserving the hard constraints: canonical TransportPacket only, Gate-only routing, and no legacy fallback path.

# filename: src/constellation_gate/services/admin_registration_service.py
from __future__ import annotations

from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry
from constellation_gate.schemas.registry import (
    NodeRegistrationStatus,
    RegisterNodesRequest,
    RegisterNodesResponse,
)


class AdminRegistrationService:
    """
    Register worker nodes into the Gate registry.

    This service is intentionally simple and synchronous in effect, but exposed
    as async to align with the rest of the Gate service layer.
    """

    def __init__(self, registry: NodeRegistry, *, admin_token: str | None = None) -> None:
        self._registry = registry
        self._admin_token = admin_token.strip() if admin_token is not None else None

    async def register(
        self,
        *,
        request: RegisterNodesRequest,
        overwrite: bool,
        presented_token: str | None,
    ) -> RegisterNodesResponse:
        self._authorize(presented_token)

        statuses: list[NodeRegistrationStatus] = []
        for node_name, registration_input in request.root.items():
            registration = NodeRegistration(
                node_name=node_name,
                internal_url=registration_input.internal_url,
                supported_actions=tuple(registration_input.supported_actions),
                priority_class=registration_input.priority_class,
                max_concurrent=registration_input.max_concurrent,
                health_endpoint=registration_input.health_endpoint,
                timeout_ms=registration_input.timeout_ms,
                metadata=dict(registration_input.metadata),
                healthy=True,
                active_requests=0,
            )
            self._registry.register_node(node_name, registration, overwrite=overwrite)
            statuses.append(
                NodeRegistrationStatus(
                    node_name=node_name.strip().lower(),
                    healthy=True,
                    registered=True,
                )
            )

        return RegisterNodesResponse(
            registered=statuses,
            total_nodes=len(statuses),
        )

    def _authorize(self, presented_token: str | None) -> None:
        if self._admin_token is None:
            return
        if presented_token is None or presented_token.strip() != self._admin_token:
            raise PermissionError("admin token required or invalid")
# filename: src/constellation_gate/services/workflow_service.py
from __future__ import annotations

from constellation_gate.orchestration.workflow_engine import WorkflowEngine
from constellation_node_sdk.transport.packet import TransportPacket


class WorkflowService:
    """
    Thin service wrapper around the Gate workflow engine.
    """

    def __init__(self, engine: WorkflowEngine) -> None:
        self._engine = engine

    async def maybe_execute(self, packet: TransportPacket) -> TransportPacket:
        if self._engine.has_workflow(packet.header.action):
            return await self._engine.execute(packet)
        return packet
# filename: src/constellation_gate/api/dependencies.py
from __future__ import annotations

from functools import lru_cache

from constellation_gate.boundary.ingress_validator import IngressValidator
from constellation_gate.config.settings import GateSettings, get_settings
from constellation_gate.orchestration.workflow_engine import WorkflowEngine
from constellation_gate.routing.dispatch import Dispatcher
from constellation_gate.routing.node_registry import NodeRegistry
from constellation_gate.services.admin_registration_service import AdminRegistrationService
from constellation_gate.services.execute_service import ExecuteService
from constellation_gate.services.registry_query_service import RegistryQueryService
from constellation_gate.services.workflow_service import WorkflowService


@lru_cache
def get_registry() -> NodeRegistry:
    return NodeRegistry()


@lru_cache
def get_ingress_validator() -> IngressValidator:
    settings = get_settings()
    registry = get_registry()
    return IngressValidator(
        local_node=settings.local_node,
        known_nodes_provider=registry.known_nodes,
        allowed_actions=settings.allowed_actions,
        allowed_packet_types=settings.allowed_packet_types,
        allowed_clock_skew_seconds=settings.allowed_clock_skew_seconds,
        max_packet_bytes=settings.max_packet_bytes,
        max_hop_depth=settings.max_hop_depth,
        max_delegation_depth=settings.max_delegation_depth,
        max_attachments=settings.max_attachments,
        max_attachment_size_bytes=settings.max_attachment_size_bytes,
        allowed_attachment_schemes=settings.attachment_allowed_schemes,
        allow_private_attachment_hosts=settings.allow_private_attachment_hosts,
        require_signature=settings.require_signature,
        key_resolver=settings.resolve_verifying_key,
        required_idempotency_actions=settings.required_idempotency_actions,
        replay_enabled=settings.replay_enabled,
        dev_mode=settings.dev_mode,
        verify_hop_signatures=settings.verify_hop_signatures,
        hop_key_resolver=settings.resolve_verifying_key,
    )


@lru_cache
def get_dispatcher() -> Dispatcher:
    settings = get_settings()
    return Dispatcher(
        local_node=settings.local_node,
        registry=get_registry(),
    )


@lru_cache
def get_workflow_engine() -> WorkflowEngine:
    settings = get_settings()
    return WorkflowEngine(
        definitions={},
        dispatcher=get_dispatcher(),
        local_node=settings.local_node,
    )


@lru_cache
def get_execute_service() -> ExecuteService:
    settings = get_settings()
    return ExecuteService(
        local_node=settings.local_node,
        ingress_validator=get_ingress_validator(),
        dispatcher=get_dispatcher(),
        workflow_engine=get_workflow_engine(),
        registry=get_registry(),
    )


@lru_cache
def get_admin_registration_service() -> AdminRegistrationService:
    settings = get_settings()
    return AdminRegistrationService(
        get_registry(),
        admin_token=settings.admin_token,
    )


@lru_cache
def get_registry_query_service() -> RegistryQueryService:
    return RegistryQueryService(get_registry())


@lru_cache
def get_workflow_service() -> WorkflowService:
    return WorkflowService(get_workflow_engine())


def get_gate_settings() -> GateSettings:
    return get_settings()
# filename: src/constellation_gate/api/errors.py
from __future__ import annotations

from fastapi import HTTPException

from constellation_gate.boundary.ingress_validator import IngressValidationError
from constellation_gate.boundary.routing_policy import RoutingPolicyError


def to_http_exception(exc: Exception) -> HTTPException:
    """
    Map Gate-layer exceptions to safe HTTP responses.
    """
    if isinstance(exc, IngressValidationError):
        return HTTPException(
            status_code=400,
            detail={
                "code": "invalid_transport_packet",
                "message": str(exc),
            },
        )

    if isinstance(exc, RoutingPolicyError):
        return HTTPException(
            status_code=403,
            detail={
                "code": "routing_policy_violation",
                "message": str(exc),
            },
        )

    if isinstance(exc, PermissionError):
        return HTTPException(
            status_code=401,
            detail={
                "code": "admin_auth_failed",
                "message": str(exc),
            },
        )

    if isinstance(exc, LookupError):
        return HTTPException(
            status_code=404,
            detail={
                "code": "not_found",
                "message": str(exc),
            },
        )

    if isinstance(exc, ValueError):
        return HTTPException(
            status_code=400,
            detail={
                "code": "invalid_request",
                "message": str(exc),
            },
        )

    return HTTPException(
        status_code=500,
        detail={
            "code": "internal_error",
            "message": "internal server error",
        },
    )
# filename: src/constellation_gate/api/main.py
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse

from constellation_gate.api.dependencies import (
    get_admin_registration_service,
    get_execute_service,
    get_gate_settings,
    get_registry_query_service,
)
from constellation_gate.api.errors import to_http_exception
from constellation_gate.schemas.registry import RegisterNodesRequest


def create_app() -> FastAPI:
    app = FastAPI(title="constellation-gate", version="1.0.0")

    @app.get("/v1/health")
    async def health() -> dict[str, Any]:
        settings = get_gate_settings()
        return {
            "status": "healthy",
            "service_name": "constellation-gate",
            "node_name": settings.local_node,
            "environment": settings.environment,
        }

    @app.post("/v1/execute")
    async def execute(request: Request) -> JSONResponse:
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("request body must be a JSON object")
            service = get_execute_service()
            packet = await service.execute(body)
            return JSONResponse(content=packet.model_dump_json_dict())
        except Exception as exc:  # noqa: BLE001
            raise to_http_exception(exc) from exc

    @app.get("/v1/registry")
    async def registry_snapshot() -> dict[str, dict]:
        try:
            service = get_registry_query_service()
            return service.snapshot()
        except Exception as exc:  # noqa: BLE001
            raise to_http_exception(exc) from exc

    @app.post("/v1/admin/register")
    async def admin_register(
        request: RegisterNodesRequest,
        overwrite: bool = Query(True),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        try:
            service = get_admin_registration_service()
            response = await service.register(
                request=request,
                overwrite=overwrite,
                presented_token=x_admin_token,
            )
            return response.model_dump(mode="json")
        except Exception as exc:  # noqa: BLE001
            raise to_http_exception(exc) from exc

    return app


app = create_app()
# filename: tests/services/test_admin_registration_service.py
from __future__ import annotations

import pytest

from constellation_gate.routing.node_registry import NodeRegistry
from constellation_gate.schemas.registry import NodeRegistrationInput, RegisterNodesRequest
from constellation_gate.services.admin_registration_service import AdminRegistrationService


@pytest.mark.asyncio
async def test_admin_registration_service_registers_nodes() -> None:
    registry = NodeRegistry()
    service = AdminRegistrationService(registry, admin_token=None)

    request = RegisterNodesRequest(
        {
            "enrich": NodeRegistrationInput(
                internal_url="http://enrich:8000",
                supported_actions=["enrich"],
            )
        }
    )

    response = await service.register(
        request=request,
        overwrite=True,
        presented_token=None,
    )

    assert response.total_nodes == 1
    assert response.registered[0].node_name == "enrich"
    assert "enrich" in registry.known_nodes()


@pytest.mark.asyncio
async def test_admin_registration_service_requires_valid_token_when_configured() -> None:
    registry = NodeRegistry()
    service = AdminRegistrationService(registry, admin_token="secret-token")

    request = RegisterNodesRequest(
        {
            "score": NodeRegistrationInput(
                internal_url="http://score:8000",
                supported_actions=["score"],
            )
        }
    )

    with pytest.raises(PermissionError):
        await service.register(
            request=request,
            overwrite=True,
            presented_token="wrong-token",
        )
# filename: tests/services/test_workflow_service.py
from __future__ import annotations

import pytest

from constellation_gate.services.workflow_service import WorkflowService
from constellation_node_sdk.transport.packet import TransportPacket, create_transport_packet


class FakeWorkflowEngine:
    def __init__(self, *, has_workflow_result: bool, response: TransportPacket) -> None:
        self._has_workflow_result = has_workflow_result
        self._response = response
        self.calls: list[TransportPacket] = []

    def has_workflow(self, name: str) -> bool:
        return self._has_workflow_result

    async def execute(self, packet: TransportPacket) -> TransportPacket:
        self.calls.append(packet)
        return self._response


@pytest.mark.asyncio
async def test_workflow_service_executes_when_workflow_exists() -> None:
    packet = create_transport_packet(
        action="full_pipeline",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )
    response = packet.derive(
        packet_type="response",
        source_node="gate",
        destination_node="client",
        reply_to="gate",
        payload={"status": "completed", "score": 99},
    )
    engine = FakeWorkflowEngine(has_workflow_result=True, response=response)
    service = WorkflowService(engine)

    result = await service.maybe_execute(packet)

    assert result.payload["score"] == 99
    assert len(engine.calls) == 1


@pytest.mark.asyncio
async def test_workflow_service_returns_original_packet_when_no_workflow_exists() -> None:
    packet = create_transport_packet(
        action="score",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )
    engine = FakeWorkflowEngine(has_workflow_result=False, response=packet)
    service = WorkflowService(engine)

    result = await service.maybe_execute(packet)

    assert result.header.packet_id == packet.header.packet_id
    assert len(engine.calls) == 0
# filename: tests/api/test_execute_endpoint.py
from __future__ import annotations

from fastapi.testclient import TestClient

from constellation_gate.api.main import create_app
from constellation_gate.api import dependencies as deps
from constellation_node_sdk.transport.packet import create_transport_packet


class FakeExecuteService:
    def __init__(self, response_packet) -> None:
        self.response_packet = response_packet
        self.calls: list[dict] = []

    async def execute(self, body: dict):
        self.calls.append(body)
        return self.response_packet


def test_execute_endpoint_returns_canonical_packet_response() -> None:
    app = create_app()
    request_packet = create_transport_packet(
        action="score",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )
    response_packet = request_packet.derive(
        packet_type="response",
        source_node="gate",
        destination_node="client",
        reply_to="gate",
        payload={"status": "completed", "score": 88},
    )
    fake_service = FakeExecuteService(response_packet)

    original = deps.get_execute_service
    deps.get_execute_service = lambda: fake_service
    try:
        client = TestClient(app)
        response = client.post("/v1/execute", json=request_packet.model_dump_json_dict())
    finally:
        deps.get_execute_service = original

    assert response.status_code == 200
    body = response.json()
    assert body["header"]["packet_type"] == "response"
    assert body["payload"]["score"] == 88
    assert len(fake_service.calls) == 1
# filename: tests/api/test_admin_register_endpoint.py
from __future__ import annotations

from fastapi.testclient import TestClient

from constellation_gate.api.main import create_app
from constellation_gate.api import dependencies as deps


class FakeAdminRegistrationService:
    async def register(self, *, request, overwrite: bool, presented_token: str | None):
        del overwrite, presented_token
        return type(
            "Response",
            (),
            {
                "model_dump": lambda self, mode="json": {
                    "registered": [
                        {
                            "node_name": next(iter(request.root.keys())),
                            "healthy": True,
                            "registered": True,
                        }
                    ],
                    "total_nodes": 1,
                }
            },
        )()


def test_admin_register_endpoint_registers_node() -> None:
    app = create_app()
    original = deps.get_admin_registration_service
    deps.get_admin_registration_service = lambda: FakeAdminRegistrationService()
    try:
        client = TestClient(app)
        response = client.post(
            "/v1/admin/register?overwrite=true",
            headers={"X-Admin-Token": "secret"},
            json={
                "enrich": {
                    "internal_url": "http://enrich:8000",
                    "supported_actions": ["enrich"],
                    "priority_class": "P2",
                    "max_concurrent": 50,
                    "health_endpoint": "/v1/health",
                    "timeout_ms": 30000,
                    "metadata": {},
                }
            },
        )
    finally:
        deps.get_admin_registration_service = original

    assert response.status_code == 200
    body = response.json()
    assert body["total_nodes"] == 1
    assert body["registered"][0]["node_name"] == "enrich"
# filename: tests/api/test_registry_endpoint.py
from __future__ import annotations

from fastapi.testclient import TestClient

from constellation_gate.api.main import create_app
from constellation_gate.api import dependencies as deps


class FakeRegistryQueryService:
    def snapshot(self) -> dict[str, dict]:
        return {
            "enrich": {
                "node_name": "enrich",
                "internal_url": "http://enrich:8000",
                "supported_actions": ["enrich"],
                "healthy": True,
                "active_requests": 0,
            }
        }


def test_registry_endpoint_returns_registry_snapshot() -> None:
    app = create_app()
    original = deps.get_registry_query_service
    deps.get_registry_query_service = lambda: FakeRegistryQueryService()
    try:
        client = TestClient(app)
        response = client.get("/v1/registry")
    finally:
        deps.get_registry_query_service = original

    assert response.status_code == 200
    body = response.json()
    assert "enrich" in body
    assert body["enrich"]["healthy"] is True
This pass gives you:

admin node registration service

workflow service wrapper

dependency wiring for the Gate app

API error mapping

runnable FastAPI app with /v1/health, /v1/execute, /v1/registry, and /v1/admin/register

service/API tests for the full admin and read surface

🚀 Your Next Prompt

Generate a 12-file pass to harden and finish repo assembly: complete runnable files for src/constellation_gate/__init__.py, api/__init__.py, boundary/__init__.py, routing/__init__.py, orchestration/__init__.py, services/__init__.py, schemas/__init__.py, plus tests/api/test_health_endpoint.py, tests/architecture/test_no_direct_node_to_node.py, tests/architecture/test_gate_dispatch_authority.py, tests/architecture/test_lineage_reentry.py, and tests/integration/test_end_to_end.py, all aligned with the current Gate kernel and TransportPacket contract.

Reply Y to use this as your next prompt!


What’s left to complete the original filetree for SDK repo?

For constellation-node-sdk, you have the core mostly in place. What’s left is the rest of the original file tree, mainly in four buckets:

1. Still missing in src/constellation_node_sdk/
transport/
codec.py

lineage.py

gate/
registration.py exists

client.py exists

config.py exists

policy.py exists

errors.py exists

So Gate layer is basically complete.

runtime/
app.py exists

config.py exists

execution.py exists

handlers.py exists

preflight.py exists

observability.py exists

errors.py exists

lifecycle.py exists

Runtime layer is basically complete.

orchestrator/
You have:

base.py

state.py

retry.py

merge.py

packet_builder.py

step_executor.py

__init__.py

Still missing from the original tree:

no additional orchestrator files are required unless you want the earlier placeholder names to map 1:1, but functionally this layer is close

repo root/package metadata
Still missing:

py.typed

2. Still missing at repo root
Docs / contracts / examples / scripts
From the original SDK tree, these are still not built:

root
README.md

ARCHITECTURE.md

CHANGELOG.md

DEFERRED.md

pyproject.toml

.env.example

.gitignore

Makefile

contracts/
transport-packet.schema.json

TRANSPORT_PACKET_SPEC.md

NODE_REGISTRATION_SPEC.md

ROUTING_POLICY_SPEC.md

docs/
transport-packet.md

gate-client.md

node-runtime.md

orchestrator-pattern.md

migration-from-packet-envelope.md

examples/
worker_node/README.md

worker_node/app.py

worker_node/handlers.py

worker_node/spec.yaml

orchestrator_node/README.md

orchestrator_node/app.py

orchestrator_node/handlers.py

orchestrator_node/spec.yaml

packets/simple_request.json

packets/orchestrated_request.json

packets/replay_request.json

scripts/
validate_contracts.py

generate_schema.py

release.sh

3. Tests still missing
You have only part of the orchestrator tests. The original SDK tree still needs:

tests/transport/
test_transport_packet.py

test_hashing.py

test_codec.py

test_lineage.py

test_hop_trace.py

test_tenant.py

test_provenance.py

tests/security/
test_signing.py

test_verification.py

test_validation.py

test_delegation.py

tests/gate/
test_client.py

test_registration.py

test_policy.py

tests/runtime/
test_app.py

test_handlers.py

test_execution.py

test_preflight.py

tests/orchestrator/
Already generated:

test_packet_builder.py

test_merge.py

test_retry.py

Still missing:

test_step_executor.py

optionally test_state.py if you want full coverage, though that was not explicitly in the original tree

tests/integration/
test_worker_to_gate_roundtrip.py

test_orchestrator_via_gate.py

test_gate_only_egress.py

root test support
tests/conftest.py

4. Functional gaps, not just files
Even where files exist, a few important completion items remain:

transport completeness
transport/codec.py to make serialization/deserialization explicit

transport/lineage.py to centralize lineage validation and derivation helpers instead of relying only on packet methods

package polish
top-level __init__.py is in place, but the repo still needs:

install metadata

typed package marker

public API docs

schema generation flow

runnable examples
Right now the SDK is mostly library code. The original tree also assumed:

a minimal worker node example

a minimal orchestrator node example

example packets for docs/tests

production confidence
The biggest missing value is test depth:

transport tests

security tests

Gate client tests

runtime app tests

end-to-end integration tests

Bottom line
Core SDK implementation status
Mostly built

transport core: nearly complete

security: built

Gate client: built

runtime: built

orchestrator: mostly built

Biggest missing areas
Not built yet

transport/codec.py

transport/lineage.py

most tests

all docs/contracts/examples/scripts

repo packaging files

py.typed

If you want the shortest “done enough to use” finish line
The minimum remaining high-value SDK files are:

transport/codec.py

transport/lineage.py

tests/transport/*

tests/security/*

tests/gate/test_client.py

tests/runtime/test_app.py

tests/integration/test_gate_only_egress.py

pyproject.toml

README.md

py.typed

That gets you from “mostly implemented code” to “installable, testable SDK”.

🚀 Your Next Prompt

Generate a 12-file SDK completion pass covering the highest-value missing pieces: complete runnable files for src/constellation_node_sdk/transport/codec.py, transport/lineage.py, py.typed, tests/transport/test_transport_packet.py, tests/transport/test_hashing.py, tests/transport/test_codec.py, tests/transport/test_lineage.py, tests/security/test_signing.py, tests/security/test_verification.py, tests/security/test_validation.py, tests/gate/test_client.py, and tests/runtime/test_app.py.

Reply Y to use this as your next prompt!


Y

Strategic reasoning:

This is the right SDK completion pass. The biggest remaining leverage on the SDK side is not more architecture, it is closing the transport contract loop with codec + lineage helpers and real test coverage. These 12 files move the repo from “core mostly exists” to “installable library with transport correctness checks.”

# filename: src/constellation_node_sdk/transport/codec.py
from __future__ import annotations

from typing import Any

from constellation_node_sdk.transport.packet import TransportPacket


def encode_transport_packet(packet: TransportPacket) -> dict[str, Any]:
    """
    Encode a TransportPacket into a JSON-safe dict.
    """
    return packet.model_dump_json_dict()


def decode_transport_packet(payload: dict[str, Any]) -> TransportPacket:
    """
    Decode a JSON object into a canonical TransportPacket.
    """
    if not isinstance(payload, dict):
        raise ValueError("transport payload must be a JSON object")
    return TransportPacket.model_validate(payload)
# filename: src/constellation_node_sdk/transport/lineage.py
from __future__ import annotations

from constellation_node_sdk.transport.errors import TransportValidationError
from constellation_node_sdk.transport.models import TransportLineage
from constellation_node_sdk.transport.packet import TransportPacket


def derive_lineage(parent: TransportPacket) -> TransportLineage:
    """
    Derive lineage for a semantic child packet.
    """
    return TransportLineage(
        parent_id=parent.header.packet_id,
        root_id=parent.lineage.root_id,
        generation=parent.lineage.generation + 1,
    )


def validate_parent_child_lineage(parent: TransportPacket, child: TransportPacket) -> None:
    """
    Validate that a child packet was correctly derived from a parent packet.
    """
    if child.lineage.parent_id != parent.header.packet_id:
        raise TransportValidationError("child parent_id does not match parent packet_id")
    if child.lineage.root_id != parent.lineage.root_id:
        raise TransportValidationError("child root_id does not match parent root_id")
    if child.lineage.generation != parent.lineage.generation + 1:
        raise TransportValidationError("child generation must increment by 1")
# filename: src/constellation_node_sdk/py.typed
# filename: tests/transport/test_transport_packet.py
from __future__ import annotations

from constellation_node_sdk.transport.packet import TransportPacket, create_transport_packet
from constellation_node_sdk.transport.provenance import RoutingProvenance


def test_create_transport_packet_builds_canonical_root_packet() -> None:
    packet = create_transport_packet(
        action="enrich",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )

    assert isinstance(packet, TransportPacket)
    assert packet.header.packet_type == "request"
    assert packet.header.action == "enrich"
    assert packet.address.source_node == "client"
    assert packet.address.destination_node == "gate"
    assert packet.lineage.parent_id is None
    assert packet.lineage.root_id == packet.header.packet_id
    assert packet.lineage.generation == 0
    assert packet.provenance.origin_kind == "client"
    assert packet.security.payload_hash
    assert packet.security.transport_hash


def test_transport_packet_derive_creates_child_with_incremented_lineage() -> None:
    parent = create_transport_packet(
        action="workflow.execute",
        payload={"workflow": "full_pipeline"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )

    child = parent.derive(
        packet_type="request",
        action="enrich",
        source_node="orchestrator",
        destination_node="gate",
        reply_to="orchestrator",
        payload={"entity_id": "42"},
        provenance=RoutingProvenance(
            origin_kind="node",
            requested_action="enrich",
            resolved_by_gate=False,
            original_source_node="orchestrator",
        ),
    )

    assert child.header.packet_id != parent.header.packet_id
    assert child.lineage.parent_id == parent.header.packet_id
    assert child.lineage.root_id == parent.lineage.root_id
    assert child.lineage.generation == parent.lineage.generation + 1
    assert child.address.source_node == "orchestrator"
    assert child.address.destination_node == "gate"
    assert child.security.transport_hash != parent.security.transport_hash


def test_transport_packet_with_hop_preserves_transport_hash() -> None:
    from constellation_node_sdk.transport.hop_trace import make_ingress_hop

    packet = create_transport_packet(
        action="enrich",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )

    original_transport_hash = packet.security.transport_hash
    hopped = packet.with_hop(
        make_ingress_hop(
            packet=packet,
            node="gate",
            action="enrich",
            status="validated",
        )
    )

    assert len(hopped.hop_trace) == 1
    assert hopped.security.transport_hash == original_transport_hash
    assert hopped.security.payload_hash == packet.security.payload_hash
# filename: tests/transport/test_hashing.py
from __future__ import annotations

from constellation_node_sdk.transport.hashing import canonical_json, compute_payload_hash, compute_transport_hash
from constellation_node_sdk.transport.packet import create_transport_packet


def test_canonical_json_is_stable_for_equivalent_dict_orderings() -> None:
    left = {"b": 2, "a": 1, "nested": {"z": 9, "x": 3}}
    right = {"nested": {"x": 3, "z": 9}, "a": 1, "b": 2}

    assert canonical_json(left) == canonical_json(right)


def test_compute_payload_hash_is_stable_for_equivalent_payloads() -> None:
    left = {"b": 2, "a": 1}
    right = {"a": 1, "b": 2}

    assert compute_payload_hash(left) == compute_payload_hash(right)


def test_compute_transport_hash_changes_when_semantic_payload_changes() -> None:
    packet = create_transport_packet(
        action="score",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )
    mutated = packet.derive(
        action="score",
        source_node="client",
        destination_node="gate",
        reply_to="client",
        payload={"entity_id": "43"},
    )

    assert compute_transport_hash(packet) != compute_transport_hash(mutated)
# filename: tests/transport/test_codec.py
from __future__ import annotations

import pytest

from constellation_node_sdk.transport.codec import decode_transport_packet, encode_transport_packet
from constellation_node_sdk.transport.packet import create_transport_packet


def test_encode_decode_transport_packet_round_trip() -> None:
    packet = create_transport_packet(
        action="enrich",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )

    encoded = encode_transport_packet(packet)
    decoded = decode_transport_packet(encoded)

    assert decoded.header.packet_id == packet.header.packet_id
    assert decoded.security.transport_hash == packet.security.transport_hash
    assert decoded.payload == packet.payload


def test_decode_transport_packet_rejects_non_object() -> None:
    with pytest.raises(ValueError):
        decode_transport_packet(["not", "an", "object"])  # type: ignore[arg-type]
# filename: tests/transport/test_lineage.py
from __future__ import annotations

import pytest

from constellation_node_sdk.transport.lineage import derive_lineage, validate_parent_child_lineage
from constellation_node_sdk.transport.packet import create_transport_packet


def test_derive_lineage_matches_parent_relationship() -> None:
    parent = create_transport_packet(
        action="workflow.execute",
        payload={"workflow": "full_pipeline"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )

    lineage = derive_lineage(parent)

    assert lineage.parent_id == parent.header.packet_id
    assert lineage.root_id == parent.lineage.root_id
    assert lineage.generation == parent.lineage.generation + 1


def test_validate_parent_child_lineage_accepts_valid_child() -> None:
    parent = create_transport_packet(
        action="workflow.execute",
        payload={},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )
    child = parent.derive(
        action="enrich",
        source_node="orchestrator",
        destination_node="gate",
        reply_to="orchestrator",
        payload={"entity_id": "42"},
    )

    validate_parent_child_lineage(parent, child)


def test_validate_parent_child_lineage_rejects_invalid_child() -> None:
    parent = create_transport_packet(
        action="workflow.execute",
        payload={},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )
    child = create_transport_packet(
        action="enrich",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="orchestrator",
        reply_to="orchestrator",
    )

    with pytest.raises(Exception):
        validate_parent_child_lineage(parent, child)
# filename: tests/security/test_signing.py
from __future__ import annotations

from constellation_node_sdk.security.signing import recompute_transport_core, sign_transport_packet
from constellation_node_sdk.transport.packet import create_transport_packet


def test_recompute_transport_core_clears_signature_and_preserves_hash_domain() -> None:
    packet = create_transport_packet(
        action="score",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )

    recomputed = recompute_transport_core(packet)

    assert recomputed.security.payload_hash == packet.security.payload_hash
    assert recomputed.security.transport_hash == packet.security.transport_hash
    assert recomputed.security.signature is None


def test_sign_transport_packet_with_hmac_signs_transport_hash() -> None:
    packet = create_transport_packet(
        action="score",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )

    signed = sign_transport_packet(
        packet,
        key="super-secret",
        key_id="hmac-key-1",
        algorithm="hmac-sha256",
    )

    assert signed.security.signature is not None
    assert signed.security.signature_algorithm == "hmac-sha256"
    assert signed.security.signing_key_id == "hmac-key-1"
# filename: tests/security/test_verification.py
from __future__ import annotations

from constellation_node_sdk.security.signing import sign_transport_packet
from constellation_node_sdk.security.verification import verify_transport_packet_signature
from constellation_node_sdk.transport.packet import create_transport_packet


def test_verify_transport_packet_signature_returns_true_for_valid_hmac_signature() -> None:
    packet = create_transport_packet(
        action="enrich",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )
    signed = sign_transport_packet(
        packet,
        key="super-secret",
        key_id="hmac-key-1",
        algorithm="hmac-sha256",
    )

    assert verify_transport_packet_signature(
        signed,
        key_resolver={"hmac-key-1": "super-secret"},
    ) is True


def test_verify_transport_packet_signature_returns_false_for_unsigned_packet() -> None:
    packet = create_transport_packet(
        action="enrich",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )

    assert verify_transport_packet_signature(
        packet,
        key_resolver={"hmac-key-1": "super-secret"},
    ) is False
# filename: tests/security/test_validation.py
from __future__ import annotations

import pytest

from constellation_node_sdk.security.signing import sign_transport_packet
from constellation_node_sdk.security.validation import validate_transport_packet
from constellation_node_sdk.transport.packet import create_transport_packet


def test_validate_transport_packet_accepts_valid_signed_packet() -> None:
    packet = create_transport_packet(
        action="score",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )
    signed = sign_transport_packet(
        packet,
        key="super-secret",
        key_id="hmac-key-1",
        algorithm="hmac-sha256",
    )

    validate_transport_packet(
        signed,
        key_resolver={"hmac-key-1": "super-secret"},
        require_signature=True,
    )


def test_validate_transport_packet_rejects_wrong_destination_for_local_node() -> None:
    packet = create_transport_packet(
        action="score",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )

    with pytest.raises(Exception):
        validate_transport_packet(
            packet,
            local_node="worker-a",
        )


def test_validate_transport_packet_rejects_missing_signature_when_required() -> None:
    packet = create_transport_packet(
        action="score",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )

    with pytest.raises(Exception):
        validate_transport_packet(
            packet,
            require_signature=True,
            dev_mode=False,
        )
# filename: tests/gate/test_client.py
from __future__ import annotations

import httpx
import pytest

from constellation_node_sdk.gate.client import GateClient
from constellation_node_sdk.gate.config import GateClientConfig
from constellation_node_sdk.transport.packet import create_transport_packet
from constellation_node_sdk.transport.provenance import RoutingProvenance


class MockTransport(httpx.AsyncBaseTransport):
    def __init__(self, response_body: dict) -> None:
        self._response_body = response_body
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(
            status_code=200,
            json=self._response_body,
            request=request,
        )


@pytest.mark.asyncio
async def test_gate_client_sends_canonical_packet_to_gate() -> None:
    response_packet = create_transport_packet(
        action="enrich",
        payload={"status": "completed"},
        tenant="tenant-a",
        destination_node="orchestrator",
        source_node="gate",
        reply_to="gate",
    )
    transport = MockTransport(response_packet.model_dump_json_dict())

    original_async_client = httpx.AsyncClient

    class PatchedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    httpx.AsyncClient = PatchedAsyncClient  # type: ignore[assignment]
    try:
        config = GateClientConfig(
            gate_url="http://gate:8000",
            local_node="orchestrator",
            timeout_seconds=5.0,
            require_signature=False,
            verify_response_signatures=False,
        )
        client = GateClient(config)

        packet = create_transport_packet(
            action="enrich",
            payload={"entity_id": "42"},
            tenant="tenant-a",
            destination_node="gate",
            source_node="orchestrator",
            reply_to="orchestrator",
            provenance=RoutingProvenance(
                origin_kind="node",
                requested_action="enrich",
                resolved_by_gate=False,
                original_source_node="orchestrator",
            ),
        )

        response = await client.send_to_gate(packet)

        assert response.payload["status"] == "completed"
        assert len(transport.requests) == 1
        assert str(transport.requests[0].url) == "http://gate:8000/v1/execute"
    finally:
        httpx.AsyncClient = original_async_client  # type: ignore[assignment]
# filename: tests/runtime/test_app.py
from __future__ import annotations

from fastapi.testclient import TestClient

from constellation_node_sdk.runtime.app import create_node_app
from constellation_node_sdk.runtime.config import NodeRuntimeConfig
from constellation_node_sdk.runtime.handlers import clear_handlers, register_handler
from constellation_node_sdk.runtime.lifecycle import NoOpLifecycle
from constellation_node_sdk.transport.packet import create_transport_packet


def test_node_app_health_and_execute_endpoints_work() -> None:
    clear_handlers()

    @register_handler("score")
    async def handle_score(_tenant: str, payload: dict) -> dict:
        return {
            "status": "completed",
            "score": 91,
            "entity_id": payload["entity_id"],
        }

    config = NodeRuntimeConfig(
        environment="test",
        node_name="score",
        service_name="score-node",
        service_version="1.0.0",
        dev_mode=True,
        require_signature=False,
        signing_algorithm="hmac-sha256",
        allowed_actions=("score",),
        allowed_packet_types=("request",),
        require_idempotency_for_actions=(),
        allowed_clock_skew_seconds=30,
        max_packet_bytes=262_144,
        max_hop_depth=64,
        max_delegation_depth=8,
        max_attachments=0,
        max_attachment_size_bytes=0,
        attachment_allowed_schemes=(),
        allow_private_attachment_hosts=False,
        replay_enabled=True,
        verify_hop_signatures=False,
        gate_url="http://gate:8000",
        host="127.0.0.1",
        port=8001,
    )

    app = create_node_app(
        service_name="score-node",
        version="1.0.0",
        lifecycle_hook=NoOpLifecycle(),
        config=config,
        auto_register_with_gate=False,
    )

    with TestClient(app) as client:
        health = client.get("/v1/health")
        assert health.status_code == 200
        assert health.json()["ready"] is True

        packet = create_transport_packet(
            action="score",
            payload={"entity_id": "42"},
            tenant="tenant-a",
            destination_node="score",
            source_node="gate",
            reply_to="gate",
        )
        response = client.post("/v1/execute", json=packet.model_dump_json_dict())
        assert response.status_code == 200
        body = response.json()
        assert body["header"]["packet_type"] == "response"
        assert body["payload"]["score"] == 91
        assert body["payload"]["entity_id"] == "42"
This pass gives you the highest-value remaining SDK completion slice:

explicit transport codec

explicit lineage helper module

typed package marker

transport tests

security tests

Gate client test

runtime app test

What still remains after this pass
Mostly non-core completion work:

tests/transport/test_hop_trace.py

tests/transport/test_tenant.py

tests/transport/test_provenance.py

tests/security/test_delegation.py

tests/gate/test_registration.py

tests/gate/test_policy.py

tests/runtime/test_handlers.py

tests/runtime/test_execution.py

tests/runtime/test_preflight.py

tests/orchestrator/test_step_executor.py

tests/integration/*

repo root packaging/docs/examples/scripts

🚀 Your Next Prompt

Generate a 12-file SDK hardening pass for the remaining highest-value tests and packaging: complete runnable files for tests/transport/test_hop_trace.py, tests/transport/test_tenant.py, tests/transport/test_provenance.py, tests/security/test_delegation.py, tests/gate/test_registration.py, tests/gate/test_policy.py, tests/runtime/test_handlers.py, tests/runtime/test_execution.py, tests/runtime/test_preflight.py, tests/orchestrator/test_step_executor.py, tests/conftest.py, and pyproject.toml.

Reply Y to use this as your next prompt!


Make max files per pass within token limits for max velocity 

Quality: Top Frontier AI Lab, enterprise-grade, production-ready, L9 repo aligned quality! 


Make next file generation wave. Max per pass within token limits 


Thought for 17s

Are these still only SdK files?

No — we just finished the SDK pass.