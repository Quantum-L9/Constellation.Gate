2. constellation-gate

> **Disk vs this tree:** [inventory-vs-target.md](inventory-vs-target.md) compares this tree to the repo (filename-based parse). As of last update: **3** target paths still missing on disk, **~87** on-disk files not listed below.

constellation-gate/
├── README.md
├── ARCHITECTURE.md
├── CHANGELOG.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── Makefile
│
├── docs/
│   ├── gate-kernel.md
│   ├── ingress-policy.md
│   ├── action-resolution.md
│   ├── dispatch-semantics.md
│   ├── workflow-engine.md
│   └── migration-from-legacy-gate.md
│
├── contracts/
│   ├── README.md
│   ├── transport-packet.schema.json
│   ├── TRANSPORT_PACKET_SPEC.md
│   ├── NODE_REGISTRATION_SPEC.md
│   ├── ROUTING_POLICY_SPEC.md
│   ├── WORKFLOW_SPEC.md
│   └── ADMIN_REGISTER_SPEC.md
│
├── src/
│   └── constellation_gate/
│       ├── __init__.py
│       │
│       ├── api/
│       │   ├── __init__.py
│       │   ├── main.py
│       │   ├── middleware.py
│       │   ├── dependencies.py
│       │   └── errors.py
│       │
│       ├── config/
│       │   ├── __init__.py
│       │   ├── settings.py
│       │   ├── node_registry.yaml
│       │   ├── priorities.yaml
│       │   └── workflows.yaml
│       │
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
│       │
│       ├── routing/
│       │   ├── __init__.py
│       │   ├── node_registry.py
│       │   ├── resolver.py
│       │   ├── dispatch.py
│       │   ├── health_monitor.py
│       │   └── priority_queue.py
│       │
│       ├── orchestration/
│       │   ├── __init__.py
│       │   ├── workflow_engine.py
│       │   ├── workflow_models.py
│       │   └── condition_eval.py
│       │
│       ├── services/
│       │   ├── __init__.py
│       │   ├── execute_service.py
│       │   ├── admin_registration_service.py
│       │   ├── registry_query_service.py
│       │   └── workflow_service.py
│       │
│       ├── schemas/
│       │   ├── __init__.py
│       │   ├── registry.py
│       │   └── workflow.py
│       │
│       └── observability/
│           ├── __init__.py
│           ├── logging.py
│           ├── metrics.py
│           ├── tracing.py
│           └── audit_logger.py
│
├── tests/
│   ├── conftest.py
│   ├── boundary/
│   │   ├── test_ingress_validator.py
│   │   ├── test_routing_policy.py
│   │   ├── test_command_factory.py
│   │   ├── test_response_factory.py
│   │   ├── test_failure_factory.py
│   │   └── test_transport_codec.py
│   ├── routing/
│   │   ├── test_registry.py
│   │   ├── test_resolver.py
│   │   ├── test_dispatch.py
│   │   ├── test_health_monitor.py
│   │   └── test_priority_queue.py
│   ├── orchestration/
│   │   ├── test_workflow_engine.py
│   │   ├── test_workflow_models.py
│   │   └── test_condition_eval.py
│   ├── services/
│   │   ├── test_execute_service.py
│   │   ├── test_admin_registration_service.py
│   │   ├── test_registry_query_service.py
│   │   └── test_workflow_service.py
│   ├── api/
│   │   ├── test_execute_endpoint.py
│   │   ├── test_admin_register_endpoint.py
│   │   └── test_registry_endpoint.py
│   ├── architecture/
│   │   ├── test_gate_dispatch_authority.py
│   │   ├── test_no_direct_node_to_node.py
│   │   ├── test_lineage_reentry.py
│   │   ├── test_gate_only_routing.py
│   │   └── test_orchestrator_via_gate.py
│   └── integration/
│       ├── test_end_to_end.py
│       ├── test_ingress_hardening.py
│       ├── test_policy_runtime_response.py
│       └── test_production_startup.py
│
├── deploy/
│   ├── README_DEPLOY.md
│   ├── docker-compose.yml
│   ├── prometheus.rules.yml
│   └── terraform/
│       ├── main.tf
│       ├── variables.tf
│       ├── outputs.tf
│       ├── versions.tf
│       └── cloud-init.yaml.tftpl
│
├── scripts/
│   ├── entrypoint.sh
│   ├── predeploy_check.py
│   ├── migrate_registry.py
│   └── sync_contracts_from_sdk.sh
│
└── examples/
    ├── registry/
    │   └── node_registry.yaml
    └── workflows/
        └── full_pipeline.yaml




TransportPacket
Rename targets
PacketEnvelope       -> TransportPacket
create_packet        -> create_transport_packet
validate_packet      -> validate_transport_packet
sign_packet          -> sign_transport_packet
deflate_egress       -> encode_transport_packet
inflate_ingress      -> decode_transport_packet
Type components
These should keep the same underlying concepts but align naming around transport:

PacketHeader         -> TransportHeader
PacketAddress        -> TransportAddress
PacketSecurity       -> TransportSecurity
PacketGovernance     -> TransportGovernance
PacketLineage        -> TransportLineage
PacketAttachment     -> TransportAttachment
HopEntry             -> TransportHop
DelegationLink       -> DelegationLink   # can stay
TenantContext        -> TenantContext    # keep