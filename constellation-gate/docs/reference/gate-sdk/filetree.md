1. constellation-node-sdk
constellation-node-sdk/
├── README.md
├── ARCHITECTURE.md
├── CHANGELOG.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── Makefile
│
├── docs/
│   ├── transport-packet.md
│   ├── gate-client.md
│   ├── node-runtime.md
│   ├── orchestrator-pattern.md
│   └── migration-from-packet-envelope.md
│
├── contracts/
│   ├── transport-packet.schema.json
│   ├── TRANSPORT_PACKET_SPEC.md
│   ├── NODE_REGISTRATION_SPEC.md
│   └── ROUTING_POLICY_SPEC.md
│
├── src/
│   └── constellation_node_sdk/
│       ├── __init__.py
│       │
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
│       │
│       ├── security/
│       │   ├── __init__.py
│       │   ├── signing.py
│       │   ├── verification.py
│       │   ├── delegation.py
│       │   ├── validation.py
│       │   └── errors.py
│       │
│       ├── gate/
│       │   ├── __init__.py
│       │   ├── client.py
│       │   ├── registration.py
│       │   ├── policy.py
│       │   ├── config.py
│       │   └── errors.py
│       │
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
│       │
│       ├── orchestrator/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── step_executor.py
│       │   ├── packet_builder.py
│       │   ├── state.py
│       │   ├── merge.py
│       │   └── retry.py
│       │
│       └── py.typed
│
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
│
├── tests/
│   ├── conftest.py
│   ├── transport/
│   │   ├── test_transport_packet.py
│   │   ├── test_hashing.py
│   │   ├── test_codec.py
│   │   ├── test_lineage.py
│   │   ├── test_hop_trace.py
│   │   ├── test_tenant.py
│   │   └── test_provenance.py
│   ├── security/
│   │   ├── test_signing.py
│   │   ├── test_verification.py
│   │   ├── test_validation.py
│   │   └── test_delegation.py
│   ├── gate/
│   │   ├── test_client.py
│   │   ├── test_registration.py
│   │   └── test_policy.py
│   ├── runtime/
│   │   ├── test_app.py
│   │   ├── test_handlers.py
│   │   ├── test_execution.py
│   │   └── test_preflight.py
│   ├── orchestrator/
│   │   ├── test_step_executor.py
│   │   ├── test_packet_builder.py
│   │   ├── test_merge.py
│   │   └── test_retry.py
│   └── integration/
│       ├── test_worker_to_gate_roundtrip.py
│       ├── test_orchestrator_via_gate.py
│       └── test_gate_only_egress.py
│
└── scripts/
    ├── validate_contracts.py
    ├── generate_schema.py
    └── release.sh



    ========



Public API intent for constellation-node-sdk
constellation_node_sdk.transport.packet.TransportPacket
constellation_node_sdk.transport.packet.create_transport_packet
constellation_node_sdk.security.signing.sign_transport_packet
constellation_node_sdk.security.validation.validate_transport_packet
constellation_node_sdk.gate.client.GateClient
constellation_node_sdk.gate.registration.register_with_gate
constellation_node_sdk.runtime.app.create_node_app
constellation_node_sdk.orchestrator.base.BaseOrchestrator
Current repo → SDK move map
chassis/packet_envelope.py     -> src/constellation_node_sdk/transport/packet.py
chassis/tenant_context.py      -> src/constellation_node_sdk/transport/tenant.py
chassis/security.py            -> src/constellation_node_sdk/security/{signing,verification,validation,delegation}.py
chassis/gate_client.py         -> src/constellation_node_sdk/gate/{client,registration}.py
chassis/chassis_app.py         -> src/constellation_node_sdk/runtime/app.py
chassis/router.py              -> split across runtime/handlers.py, runtime/execution.py, transport/codec.py
contracts/*                    -> contracts/*
client/*                       -> examples/ or separate future client packages
