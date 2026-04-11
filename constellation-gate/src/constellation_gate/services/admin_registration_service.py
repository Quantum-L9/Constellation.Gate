from __future__ import annotations

from constellation_gate.routing.node_registry import NodeRegistration, NodeRegistry
from constellation_gate.schemas.registry import (
    NodeRegistrationStatus,
    RegisterNodesRequest,
    RegisterNodesResponse,
)


class AdminRegistrationService:
    """
    Register worker nodes into the Gate registry.

    This service is intentionally simple and synchronous in effect, but exposed
    as async to align with the rest of the Gate service layer.
    """

    def __init__(self, registry: NodeRegistry, *, admin_token: str | None = None) -> None:
        self._registry = registry
        self._admin_token = admin_token.strip() if admin_token is not None else None

    async def register(
        self,
        *,
        request: RegisterNodesRequest,
        overwrite: bool,
        presented_token: str | None,
    ) -> RegisterNodesResponse:
        self._authorize(presented_token)

        statuses: list[NodeRegistrationStatus] = []
        for node_name, registration_input in request.root.items():
            registration = NodeRegistration(
                node_name=node_name,
                internal_url=registration_input.internal_url,
                supported_actions=tuple(registration_input.supported_actions),
                priority_class=registration_input.priority_class,
                max_concurrent=registration_input.max_concurrent,
                health_endpoint=registration_input.health_endpoint,
                timeout_ms=registration_input.timeout_ms,
                metadata=dict(registration_input.metadata),
                healthy=True,
                active_requests=0,
            )
            self._registry.register_node(node_name, registration, overwrite=overwrite)
            statuses.append(
                NodeRegistrationStatus(
                    node_name=node_name.strip().lower(),
                    healthy=True,
                    registered=True,
                )
            )

        return RegisterNodesResponse(
            registered=statuses,
            total_nodes=len(statuses),
        )

    def _authorize(self, presented_token: str | None) -> None:
        if self._admin_token is None:
            return
        if presented_token is None or presented_token.strip() != self._admin_token:
            raise PermissionError("admin token required or invalid")
