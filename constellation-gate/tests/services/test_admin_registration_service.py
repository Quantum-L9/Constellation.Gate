from __future__ import annotations

import pytest

from constellation_gate.routing.node_registry import NodeRegistry
from constellation_gate.schemas.registry import NodeRegistrationInput, RegisterNodesRequest
from constellation_gate.services.admin_registration_service import AdminRegistrationService


@pytest.mark.asyncio
async def test_admin_registration_service_registers_nodes() -> None:
    registry = NodeRegistry()
    service = AdminRegistrationService(registry, admin_token=None)

    request = RegisterNodesRequest(
        {
            "enrich": NodeRegistrationInput(
                internal_url="http://enrich:8000",
                supported_actions=["enrich"],
            )
        }
    )

    response = await service.register(
        request=request,
        overwrite=True,
        presented_token=None,
    )

    assert response.total_nodes == 1
    assert response.registered[0].node_name == "enrich"
    assert "enrich" in registry.known_nodes()


@pytest.mark.asyncio
async def test_admin_registration_service_requires_valid_token_when_configured() -> None:
    registry = NodeRegistry()
    service = AdminRegistrationService(registry, admin_token="secret-token")

    request = RegisterNodesRequest(
        {
            "score": NodeRegistrationInput(
                internal_url="http://score:8000",
                supported_actions=["score"],
            )
        }
    )

    with pytest.raises(PermissionError):
        await service.register(
            request=request,
            overwrite=True,
            presented_token="wrong-token",
        )
