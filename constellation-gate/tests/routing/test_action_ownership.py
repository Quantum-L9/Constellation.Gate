"""Action ownership and shared-registry enforcement (TASK-012)."""
from __future__ import annotations

import pytest

from constellation_gate.api import dependencies as deps
from constellation_gate.orchestration.workflow_engine import WorkflowEngine
from constellation_gate.orchestration.workflow_models import WorkflowDefinition, WorkflowStep
from constellation_gate.routing.action_ownership import ActionOwnershipError
from constellation_gate.routing.dispatch import Dispatcher
from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry
from constellation_gate.services.admin_registration_service import AdminRegistrationService


def _node(
    name: str,
    actions: tuple[str, ...],
    *,
    owner: str | None = None,
    url: str | None = None,
) -> NodeRegistration:
    metadata = {"owner": owner} if owner is not None else {}
    return NodeRegistration(
        node_name=name,
        internal_url=url or f"http://{name}:8000",
        supported_actions=actions,
        metadata=metadata,
    )


def test_canonical_action_requires_matching_owner() -> None:
    registry = NodeRegistry()
    with pytest.raises(ActionOwnershipError, match="owned by 'ceg'"):
        registry.register_node("eie-1", _node("eie-1", ("match",), owner="eie"))


def test_canonical_action_accepts_correct_owner() -> None:
    registry = NodeRegistry()
    registry.register_node("ceg-a", _node("ceg-a", ("match", "sync"), owner="ceg"))
    assert "ceg-a" in registry.snapshot()


def test_same_owner_replicas_allowed_for_canonical_action() -> None:
    registry = NodeRegistry()
    registry.register_node("ceg-a", _node("ceg-a", ("match",), owner="ceg"))
    registry.register_node("ceg-b", _node("ceg-b", ("match",), owner="ceg"))
    assert registry.resolve_action("match").node_name in {"ceg-a", "ceg-b"}


def test_cross_owner_collision_blocked() -> None:
    registry = NodeRegistry()
    registry.register_node("ceg-a", _node("ceg-a", ("match",), owner="ceg"))
    with pytest.raises(ActionOwnershipError, match="owned by 'ceg'|collision"):
        registry.register_node("eie-x", _node("eie-x", ("match",), owner="eie"))


def test_non_canonical_cross_owner_collision_blocked() -> None:
    registry = NodeRegistry()
    registry.register_node("worker-a", _node("worker-a", ("enrich",), owner="ceg"))
    with pytest.raises(ActionOwnershipError, match="collision"):
        registry.register_node("worker-b", _node("worker-b", ("enrich",), owner="eie"))


def test_non_canonical_actions_still_allow_multi_replica() -> None:
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
    assert registry.resolve_action("enrich").node_name == "enrich-b"


def test_admin_registration_surfaces_ownership_error() -> None:
    import asyncio

    from constellation_gate.schemas.registry import RegisterNodesRequest

    registry = NodeRegistry()
    service = AdminRegistrationService(registry, admin_token=None)
    request = RegisterNodesRequest.model_validate(
        {
            "rogue": {
                "internal_url": "http://rogue:8000",
                "supported_actions": ["converge"],
                "metadata": {"owner": "ceg"},
            }
        }
    )

    with pytest.raises(ActionOwnershipError):
        asyncio.run(service.register(request=request, overwrite=False, presented_token=None))



def test_registration_and_workflow_share_same_registry_instance() -> None:
    deps.get_registry.cache_clear()
    deps.get_dispatcher.cache_clear()
    deps.get_workflow_engine.cache_clear()
    deps.get_admin_registration_service.cache_clear()
    deps.get_gate_settings.cache_clear()
    try:
        registry = deps.get_registry()
        admin = deps.get_admin_registration_service()
        engine = deps.get_workflow_engine()
        assert admin._registry is registry
        assert engine.registry is registry
        assert engine._dispatcher is deps.get_dispatcher()
    finally:
        deps.get_registry.cache_clear()
        deps.get_dispatcher.cache_clear()
        deps.get_workflow_engine.cache_clear()
        deps.get_admin_registration_service.cache_clear()
        deps.get_gate_settings.cache_clear()


def test_workflow_rejects_unknown_step_action_when_registry_populated() -> None:
    registry = NodeRegistry()
    registry.register_node("ceg-a", _node("ceg-a", ("match",), owner="ceg"))
    dispatcher = Dispatcher(local_node="gate", registry=registry)
    definitions = {
        "full_pipeline": WorkflowDefinition(
            name="full_pipeline",
            steps=[WorkflowStep(name="bad-1", action="not-a-registered-action")],
        )
    }
    with pytest.raises(ValueError, match="shared NodeRegistry"):
        WorkflowEngine(
            definitions=definitions,
            dispatcher=dispatcher,
            local_node="gate",
            registry=registry,
        )
