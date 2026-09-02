from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
import yaml
from constellation_node_sdk.gate_authority import GateDispatchTransportConfig

from constellation_gate.boundary.ingress_validator import IngressValidator
from constellation_gate.config.settings import GateSettings, get_settings
from constellation_gate.orchestration.workflow_engine import WorkflowEngine
from constellation_gate.orchestration.workflow_models import WorkflowDefinition
from constellation_gate.routing.dispatch import Dispatcher
from constellation_gate.routing.health_monitor import HealthMonitor
from constellation_gate.routing.node_registry import NodeRegistry
from constellation_gate.runtime.http_client import AsyncHttpClientManager
from constellation_gate.runtime.node_limits import PerNodeLimiterManager
from constellation_gate.services.admin_registration_service import AdminRegistrationService
from constellation_gate.services.capability_service import CapabilityService
from constellation_gate.services.execute_service import ExecuteService
from constellation_gate.services.registry_query_service import RegistryQueryService
from constellation_gate.services.workflow_service import WorkflowService

logger = logging.getLogger(__name__)


@lru_cache
def get_registry() -> NodeRegistry:
    return NodeRegistry()


def load_static_registry() -> int:
    """Populate the registry from GATE_NODE_REGISTRY_PATH, if set.

    Called once from the ASGI lifespan. Without it the shipped
    ``config/node_registry.yaml`` was never read by anything: Gate started with
    an empty registry and the canonical ``converge`` route existed only after
    the worker's own self-registration succeeded. Returns the number of nodes
    loaded (0 when no path is configured).
    """
    settings = get_gate_settings()
    path = settings.node_registry_path
    if not path:
        return 0
    registry = get_registry()
    registry.load_from_yaml(path)
    loaded = len(registry.snapshot())
    logger.info("node registry loaded %d node(s) from '%s'", loaded, path)
    return loaded


def build_health_monitor(*, client: httpx.AsyncClient | None) -> HealthMonitor | None:
    """Build the worker health re-probe loop, or None when disabled.

    A worker is marked unhealthy on the first connection failure and, before
    this loop ran, nothing ever marked it healthy again: routing stayed dead
    until the worker re-registered or Gate restarted. The monitor re-probes
    every registered node's health endpoint at the configured cadence.
    """
    settings = get_gate_settings()
    interval = settings.health_probe_interval_seconds
    if interval <= 0:
        logger.warning(
            "GATE_HEALTH_PROBE_INTERVAL_SECONDS is 0; a worker marked unhealthy is "
            "only restored by its own re-registration"
        )
        return None
    return HealthMonitor(get_registry(), interval_seconds=interval, client=client)


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


def _pooled_client() -> httpx.AsyncClient | None:
    """Resolve the shared pooled client, or None outside an ASGI lifespan.

    Deliberately NOT lru_cached: it is called per dispatch precisely because the
    pool does not exist until ASGI startup. Caching it would freeze whatever the
    first call saw -- in practice `None`, permanently defeating the pool.

    Returning None rather than raising keeps non-ASGI callers -- scripts, unit
    tests -- on the per-call client path instead of failing on wiring.
    """
    manager = get_http_client_manager()
    if not manager.started:
        return None
    return manager.client


@lru_cache
def get_gate_dispatch_config() -> GateDispatchTransportConfig:
    """Map Gate's own security posture onto the SDK dispatch transport.

    Gate signs the worker leg with the same key it is known by, and verifies
    worker responses under the same policy it applies to its own ingress. Left
    unmapped, a Gate configured to require signatures would still dispatch
    unsigned packets to its workers -- signed at the front door, open at the
    back.
    """
    settings = get_gate_settings()
    return GateDispatchTransportConfig(
        local_gate_node=settings.local_node,
        require_signature=settings.require_signature,
        signing_key=settings.signing_key,
        signing_key_id=settings.signing_key_id,
        signing_algorithm=settings.signing_algorithm,
        verify_response_signatures=settings.require_signature,
        verifying_keys=settings.verifying_keys,
        verify_hop_signatures=settings.verify_hop_signatures,
    )


@lru_cache
def get_dispatcher() -> Dispatcher:
    settings = get_gate_settings()
    return Dispatcher(
        local_node=settings.local_node,
        registry=get_registry(),
        dispatch_config=get_gate_dispatch_config(),
        # Without these two, AsyncHttpClientManager and PerNodeLimiterManager
        # were built at startup and never consulted: every dispatch opened its
        # own client, and the per-node concurrency limiter -- the authoritative
        # admission gate before a worker call -- never ran at all.
        client_provider=_pooled_client,
        node_limits=get_node_limiter_manager(),
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
        defn_raw = _normalize_workflow_steps(defn_raw)
        try:
            definitions[name.strip().lower()] = WorkflowDefinition.model_validate(defn_raw)
        except Exception as exc:
            raise ValueError(f"'{path}': workflow '{name}' failed validation: {exc}") from exc
    return definitions


def _normalize_workflow_steps(defn_raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize legacy step syntax to the WorkflowStep schema.

    The shipped workflow config (config/workflows.yaml) predates WorkflowStep and
    uses `payload_transform` where the model expects `merge_strategy`, and omits
    per-step `name`. Map the legacy keys and synthesize deterministic step names
    (`<action>-<index>`) so both syntaxes load. Unknown keys are left intact so
    model validation still rejects genuinely malformed steps.
    """
    steps_raw = defn_raw.get("steps")
    if not isinstance(steps_raw, list):
        return defn_raw
    normalized_steps: list[Any] = []
    for index, step in enumerate(steps_raw):
        if not isinstance(step, dict):
            normalized_steps.append(step)
            continue
        step = dict(step)
        if "merge_strategy" not in step and "payload_transform" in step:
            step["merge_strategy"] = step.pop("payload_transform")
        if "name" not in step and isinstance(step.get("action"), str):
            step["name"] = f"{step['action'].strip().lower()}-{index + 1}"
        normalized_steps.append(step)
    return {**defn_raw, "steps": normalized_steps}


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
        registry=get_registry(),
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
        idempotency_ttl_seconds=settings.idempotency_ttl_seconds,
        response_margin_ms=settings.response_margin_ms,
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
def get_capability_service() -> CapabilityService:
    settings = get_gate_settings()
    return CapabilityService(get_registry(), admin_token=settings.admin_token)


@lru_cache
def get_workflow_service() -> WorkflowService:
    return WorkflowService(get_workflow_engine())
