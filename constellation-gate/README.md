# Constellation Gate

`constellation-gate` is the routing authority and execution boundary for the Constellation system.

It is the single ingress and dispatch control plane for all `TransportPacket` traffic.

## Responsibilities

Gate owns:

- ingress validation
- node-origin reentry enforcement
- action-to-node resolution
- worker dispatch
- workflow execution for composite actions
- node registration and registry inspection

Gate does **not** allow direct node-to-node peer routing.

## Core routing law

Allowed:

```text
client -> gate
node -> gate
gate -> worker
Forbidden:

node-a -> node-b
All node-origin follow-up work must return to Gate.

Canonical transport
Gate accepts and emits only:

TransportPacket

It does not expose legacy alternate request formats.

Package layout
src/constellation_gate/api/ — FastAPI surface

src/constellation_gate/boundary/ — ingress codec and routing policy

src/constellation_gate/routing/ — registry, resolver, dispatcher, queue, health

src/constellation_gate/orchestration/ — workflow engine and condition eval

src/constellation_gate/services/ — execution and admin services

src/constellation_gate/schemas/ — admin/workflow schemas

tests/ — boundary, routing, workflow, service, API, architecture, integration

Install
pip install -e .
For development:

pip install -e ".[dev]"
Run tests
pytest -q
Run Gate locally
export L9_ENVIRONMENT=local
export GATE_LOCAL_NODE=gate
export HOST=0.0.0.0
export PORT=9000

uvicorn constellation_gate.api.main:app --host 0.0.0.0 --port 9000
Endpoints
POST /v1/execute

GET /v1/health

GET /v1/registry

POST /v1/admin/register

Development principles
Gate is the sole routing authority

all worker dispatch must be Gate-authored

routing policy violations must fail closed

TransportPacket contract must stay aligned with constellation-node-sdk

architecture tests are required for routing-law changes








```markdown
