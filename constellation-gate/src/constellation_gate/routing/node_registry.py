from __future__ import annotations

from threading import RLock
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from constellation_gate.routing.action_ownership import (
    ActionOwnershipError,
    assert_registration_ownership,
    owner_for_registration,
)


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


class NoHealthyNodeError(LookupError):
    """An action Gate routes has an owner, but every owner is currently unhealthy.

    Subclasses LookupError so existing callers that catch the generic case keep
    working; the API maps it to 503 (retryable) instead of 404 (permanent).
    """


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
        with open(path, encoding="utf-8") as handle:
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

    def register_node(
        self, name: str, registration: NodeRegistration, *, overwrite: bool = False
    ) -> None:
        normalized_name = name.strip().lower()
        if not normalized_name:
            raise ValueError("name must not be empty")

        with self._lock:
            if normalized_name in self._nodes and not overwrite:
                raise ValueError(f"node already registered: {normalized_name}")
            if normalized_name != registration.node_name:
                registration = registration.model_copy(update={"node_name": normalized_name})

            existing = {
                node: tuple(reg.supported_actions)
                for node, reg in self._nodes.items()
                if not (overwrite and node == normalized_name)
            }
            existing_owners = {
                node: owner_for_registration(node_name=node, metadata=dict(reg.metadata))
                for node, reg in self._nodes.items()
                if not (overwrite and node == normalized_name)
            }
            try:
                assert_registration_ownership(
                    node_name=normalized_name,
                    supported_actions=registration.supported_actions,
                    metadata=dict(registration.metadata),
                    existing=existing,
                    existing_owners=existing_owners,
                )
            except ActionOwnershipError:
                raise

            self._nodes[normalized_name] = registration

    def all_supported_actions(self) -> set[str]:
        with self._lock:
            actions: set[str] = set()
            for registration in self._nodes.values():
                actions.update(registration.supported_actions)
            return actions

    def resolve_action(self, action: str) -> NodeRegistration:
        normalized_action = action.strip().lower()
        if not normalized_action:
            raise ValueError("action must not be empty")

        with self._lock:
            known = [
                registration
                for registration in self._nodes.values()
                if normalized_action in registration.supported_actions
            ]
            candidates = [registration for registration in known if registration.healthy]

            if not candidates:
                if known:
                    # The action IS served here; its owner is merely out of
                    # rotation. That is a transient condition (a health
                    # re-probe or re-registration restores it), so it must
                    # not wear the same "no such route" face as an unknown
                    # action -- a caller classifies 404 as permanent.
                    raise NoHealthyNodeError(
                        f"no healthy node for action: {normalized_action} "
                        f"({', '.join(sorted(r.node_name for r in known))} unhealthy)"
                    )
                raise LookupError(f"no node registered for action: {normalized_action}")

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
