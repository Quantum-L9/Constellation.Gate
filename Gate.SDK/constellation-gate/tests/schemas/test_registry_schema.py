from __future__ import annotations

import pytest

from constellation_gate.schemas.registry import (
    NodeRegistrationInput,
    RegisterNodesRequest,
    RegisterNodesResponse,
)


def test_node_registration_input_normalizes_actions() -> None:
    item = NodeRegistrationInput(
        internal_url="http://score:8000",
        supported_actions=[" Score ", "enrich"],
        priority_class="p1",
    )

    assert item.internal_url == "http://score:8000"
    assert item.supported_actions == ["score", "enrich"]
    assert item.priority_class == "P1"


def test_node_registration_input_rejects_duplicate_actions() -> None:
    with pytest.raises(ValueError):
        NodeRegistrationInput(
            internal_url="http://score:8000",
            supported_actions=["score", "score"],
        )


def test_register_nodes_request_accepts_mapping() -> None:
    request = RegisterNodesRequest(
        {
            "score": NodeRegistrationInput(
                internal_url="http://score:8000",
                supported_actions=["score"],
            )
        }
    )

    assert "score" in request.root


def test_register_nodes_response_shape() -> None:
    response = RegisterNodesResponse(
        registered=[
            {
                "node_name": "score",
                "healthy": True,
                "registered": True,
            }
        ],
        total_nodes=1,
    )

    assert response.total_nodes == 1
    assert response.registered[0].node_name == "score"
