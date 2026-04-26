from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import yaml

from constellation_gate.boundary.ingress_validator import IngressValidator
from constellation_gate.config.settings import GateSettings, get_settings
from constellation_gate.orchestration.workflow_engine import WorkflowEngine
from constellation_gate.orchestration.workflow_models import WorkflowDefinition
from constellation_gate.routing.dispatch import Dispatcher
from constellation_gate.routing.node_registry import NodeRegistry
from constellation_gate.runtime.http_client import AsyncHttpClientManager
from constellation_gate.runtime.node_limits import PerNodeLimiterManager
from constellation_gate.services.admin_registration_service import AdminRegistrationService
from constellation_gate.services.execute_service import ExecuteService
from constellation_gate.services.registry_query_service import RegistryQueryService
from constellation_gate.services.workflow_service import WorkflowService

logger = logging.getLogger(__name__)


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


def _load_workflow_definitions(path: str) -> dict[str, WorkflowDefinition]:
    """Load workflow definitions from a YAML file.

    BROKEN-001 fix: parse the YAML workflow config and return validated definitions.
    Raises ValueError if the file is missing, unreadable, or structurally invalid.
    An empty workflows key is valid (returns empty dict).
    """
    config_path = Path(path)
    if not config_path.exists():
        raise ValueError(
            f"GATE_WORKFLOW_CONFIG_PATH is set to '{path}' but the file does not exist. "
            "Fix the path or unset GATE_WORKFLOW_CONFIG_PATH to disable workflows."
        )
    with config_path.open(encoding="utf-8") as fh:
        try:
            raw = yaml.safe_load(fh)
        except yaml.YAMLError as exc:
            raise ValueError(
                f"GATE_WORKFLOW_CONFIG_PATH '{path}' is not valid YAML: {exc}"
            ) from exc

    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(
            f"GATE_WORKFLOW_CONFIG_PATH '{path}' must be a YAML mapping at the top level"
        )

    workflows_raw = raw.get("workflows", {})
    if not isinstance(workflows_raw, dict):
        raise ValueError(f"'{path}': 'workflows' key must be a YAML mapping")

    definitions: dict[str, WorkflowDefinition] = {}
    for name, defn_raw in workflows_raw.items():
        if not isinstance(defn_raw, dict):
            raise ValueError(f"'{path}': workflow '{name}' must be a YAML mapping")
        # Inject name into definition if not already present
        if "name" not in defn_raw:
            defn_raw = {"name": name, **defn_raw}
        try:
            definitions[name.strip().lower()] = WorkflowDefinition.model_validate(defn_raw)
        except Exception as exc:
            raise ValueError(f"'{path}': workflow '{name}' failed validation: {exc}") from exc
    return definitions


@lru_cache
def get_workflow_engine() -> WorkflowEngine:
    settings = get_gate_settings()
    definitions: dict[str, WorkflowDefinition] = {}

    if settings.workflow_config_path:
        # Fails fast on invalid path or malformed file — startup aborts cleanly.
        definitions = _load_workflow_definitions(settings.workflow_config_path)
        logger.info(
            "workflow engine loaded %d definitions from '%s'",
            len(definitions),
            settings.workflow_config_path,
        )
    else:
        logger.warning(
            "GATE_WORKFLOW_CONFIG_PATH is not set; workflow engine is active but has "
            "no definitions. Packets routed to workflow actions will fall through to "
            "direct dispatch."
        )

    return WorkflowEngine(
        definitions=definitions,
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
