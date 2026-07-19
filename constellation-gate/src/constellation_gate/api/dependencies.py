from __future__ import annotations

from functools import lru_cache

from constellation_gate.boundary.ingress_validator import IngressValidator
from constellation_gate.config.settings import GateSettings, get_settings
from constellation_gate.orchestration.workflow_engine import WorkflowEngine
from constellation_gate.routing.dispatch import Dispatcher
from constellation_gate.routing.node_registry import NodeRegistry
from constellation_gate.runtime.http_client import AsyncHttpClientManager
from constellation_gate.runtime.node_limits import PerNodeLimiterManager
from constellation_gate.services.admin_registration_service import AdminRegistrationService
from constellation_gate.services.execute_service import ExecuteService
from constellation_gate.services.registry_query_service import RegistryQueryService
from constellation_gate.services.workflow_service import WorkflowService


@lru_cache
def get_registry() -> NodeRegistry:
    return NodeRegistry()


@lru_cache
def get_http_client_manager() -> AsyncHttpClientManager:
    return AsyncHttpClientManager()


@lru_cache
def get_node_limiter_manager() -> PerNodeLimiterManager:
    return PerNodeLimiterManager()


@lru_cache
def get_gate_settings() -> GateSettings:
    return get_settings()


@lru_cache
def get_ingress_validator() -> IngressValidator:
    settings = get_gate_settings()
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
    settings = get_gate_settings()
    return Dispatcher(
        local_node=settings.local_node,
        registry=get_registry(),
    )


@lru_cache
def get_workflow_engine() -> WorkflowEngine:
    settings = get_gate_settings()
    return WorkflowEngine(
        definitions={},
        dispatcher=get_dispatcher(),
        local_node=settings.local_node,
    )


@lru_cache
def get_execute_service() -> ExecuteService:
    settings = get_gate_settings()
    return ExecuteService(
        local_node=settings.local_node,
        ingress_validator=get_ingress_validator(),
        dispatcher=get_dispatcher(),
        workflow_engine=get_workflow_engine(),
        registry=get_registry(),
    )


@lru_cache
def get_admin_registration_service() -> AdminRegistrationService:
    settings = get_gate_settings()
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
