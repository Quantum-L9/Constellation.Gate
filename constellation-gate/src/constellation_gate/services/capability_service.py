"""Project sanitized capability descriptors from the shared NodeRegistry."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from constellation_gate.routing.action_ownership import (
    CANONICAL_ACTION_OWNERS,
    owner_for_registration,
    required_owner_for_action,
)
from constellation_gate.routing.node_registry import NodeRegistry
from constellation_gate.schemas.capabilities import (
    CAPABILITY_CONTRACT_VERSION,
    CapabilityDescriptor,
    CapabilityListResponse,
)

PROTECTED_ACTIONS = frozenset(CANONICAL_ACTION_OWNERS)


class CapabilityAuthorizationError(PermissionError):
    """Raised when a protected capability is requested without credentials."""


class CapabilityService:
    def __init__(self, registry: NodeRegistry, *, admin_token: str | None = None) -> None:
        self._registry = registry
        self._admin_token = admin_token.strip() if admin_token is not None else None

    def list_capabilities(
        self,
        *,
        presented_token: str | None,
        include_protected: bool = False,
    ) -> CapabilityListResponse:
        authorized = self._is_authorized(presented_token)
        if include_protected and not authorized:
            raise CapabilityAuthorizationError(
                "admin token required to list protected capabilities"
            )

        descriptors = self._project(include_protected=authorized or include_protected)
        etag = self._etag_for(descriptors)
        return CapabilityListResponse(
            contract_version=CAPABILITY_CONTRACT_VERSION,
            etag=etag,
            capabilities=descriptors,
        )

    def get_capability(
        self,
        action: str,
        *,
        presented_token: str | None,
    ) -> tuple[CapabilityDescriptor, str]:
        normalized = action.strip().lower()
        if not normalized:
            raise ValueError("action must not be empty")
        if normalized in PROTECTED_ACTIONS and not self._is_authorized(presented_token):
            raise CapabilityAuthorizationError(
                f"admin token required for protected action: {normalized}"
            )

        by_action = {item.action: item for item in self._project(include_protected=True)}
        descriptor = by_action.get(normalized)
        if descriptor is None:
            # Still advertise canonical ownership even before a node registers,
            # but only for authorized callers on protected actions (already checked)
            # and for non-protected only when registered.
            required = required_owner_for_action(normalized)
            if required is not None and self._is_authorized(presented_token):
                descriptor = CapabilityDescriptor(
                    action=normalized,
                    owner=required,
                    advertised=False,
                )
            else:
                raise LookupError(f"unknown capability action: {normalized}")

        etag = self._etag_for([descriptor])
        return descriptor, etag

    def current_etag(self, *, authorized: bool) -> str:
        return self._etag_for(self._project(include_protected=authorized))

    def _project(self, *, include_protected: bool) -> list[CapabilityDescriptor]:
        actions: dict[str, str | None] = {}
        for node_name, registration in self._registry.snapshot().items():
            owner = owner_for_registration(
                node_name=node_name, metadata=dict(registration.metadata)
            )
            for action in registration.supported_actions:
                if action in PROTECTED_ACTIONS and not include_protected:
                    continue
                # Prefer canonical owner when known.
                actions[action] = required_owner_for_action(action) or owner

        # Authorized views also surface canonical actions not yet advertised.
        if include_protected:
            for action, owner in CANONICAL_ACTION_OWNERS.items():
                actions.setdefault(action, owner)

        descriptors = [
            CapabilityDescriptor(
                action=action,
                owner=owner,
                advertised=action in self._registry.all_supported_actions(),
            )
            for action, owner in sorted(actions.items())
        ]
        return descriptors

    def _etag_for(self, descriptors: list[CapabilityDescriptor]) -> str:
        payload: list[dict[str, Any]] = [item.model_dump(mode="json") for item in descriptors]
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return f'W/"{digest[:16]}"'

    def _is_authorized(self, presented_token: str | None) -> bool:
        if self._admin_token is None:
            # Dev/open mode: no token configured => treat as authorized for reads.
            return True
        if presented_token is None:
            return False
        return presented_token.strip() == self._admin_token
