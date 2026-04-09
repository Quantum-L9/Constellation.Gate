# Constellation Gate Architecture

## Purpose

Gate is the control-plane boundary for Constellation.

Nodes do not resolve peer destinations directly. They send intent to Gate, and Gate decides where work goes.

## System model

```text
Client
  ↓
TransportPacket
  ↓
Gate ingress
  ├─ decode canonical packet
  ├─ validate transport/security rules
  ├─ validate routing policy
  ├─ resolve action
  ├─ append ingress hop
  └─ dispatch
       ↓
    worker node
Architectural laws
1. Canonical transport only
Gate accepts only TransportPacket.

2. Gate-only routing authority
Only Gate may convert action intent into worker dispatch.

3. No direct node-to-node traffic
If a node-origin packet targets a peer node directly, Gate must reject it.

4. Gate-authored dispatch semantics
A valid worker dispatch packet must satisfy:

provenance.origin_kind == "gate"

provenance.resolved_by_gate == true

address.source_node == local gate node

address.destination_node == resolved worker

5. Reentry is normal
Workflow steps and follow-up work come back to Gate as node-origin packets:

orchestrator -> gate -> worker
Not:

orchestrator -> worker
Integrity planes
Transport core
Protected by transport_hash.

Covers stable semantic packet fields.

Hop journal
Protected by chained hop hashes and optional hop signatures.

Records:

ingress

dispatch

execution

response

Main subsystems
Boundary
canonical decode/encode

ingress validation

routing policy enforcement

Routing
node registry

action resolver

dispatcher

health monitoring

priority queue

Orchestration
workflow definitions

condition evaluation

sequential workflow execution

Services
execute service

admin registration

registry query

API
HTTP endpoints

dependency wiring

error translation

Execution paths
Atomic action
request -> ingress validation -> resolver -> dispatcher -> worker response
Composite workflow
request -> ingress validation -> workflow engine
         -> step packet -> dispatcher
         -> step packet -> dispatcher
         -> final response
Design objective
The Gate repo should optimize for:

authority

determinism

auditability

composability

protocol correctness


```toml
