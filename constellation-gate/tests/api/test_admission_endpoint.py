"""POST /v1/admission: Gate tells a signed consumer what its key may invoke.

The SDK's consumer activation asks; Gate answers from its own configuration
(verifying keys + L9_KEY_ALLOWED_ACTIONS_JSON) and its registry. The probe is
validated exactly like an execute request, is never dispatched, and its action
can neither be executed nor registered.
"""

from __future__ import annotations

import pytest
from constellation_node_sdk import sign_transport_packet, verify_transport_packet_signature
from constellation_node_sdk.transport.packet import TransportPacket, create_transport_packet
from fastapi.testclient import TestClient

from constellation_gate.api import dependencies as deps
from constellation_gate.api.main import create_app
from constellation_gate.boundary.ingress_validator import (
    IngressAuthorizationError,
    IngressValidationError,
    IngressValidator,
)
from constellation_gate.routing.node_registry import (
    ADMISSION_ACTION,
    NodeRegistration,
    NodeRegistry,
)
from constellation_gate.services.admission_service import AdmissionService

GATE_KEY = "gate-secret-0123456789"
KEYS = {"odoo-k1": "odoo-secret-0123456789", "eie-k1": "eie-secret-0123456789"}


def _probe(key_id: str | None, *, key: str | None = None, action: str = ADMISSION_ACTION) -> dict:
    packet = create_transport_packet(
        action=action,
        payload={},
        tenant="plasticos",
        destination_node="gate",
        source_node="odoo",
        reply_to="odoo",
    )
    if key_id is not None:
        packet = sign_transport_packet(
            packet, key=key or KEYS[key_id], key_id=key_id, algorithm="hmac-sha256"
        )
    return packet.model_dump_json_dict()


def _registry() -> NodeRegistry:
    registry = NodeRegistry()
    for name, actions in {
        "enrichment-engine": ("converge",),
        "graph": ("match", "sync"),
    }.items():
        registry.register_node(
            name,
            NodeRegistration(
                node_name=name,
                internal_url=f"http://{name}:8000",
                supported_actions=actions,
            ),
            overwrite=True,
        )
    return registry


def _policy(
    *,
    actions: tuple[str, ...] = ("converge", "match"),
    node: str = "odoo",
    tenants: tuple[str, ...] = ("plasticos",),
):
    from constellation_gate.config.settings import CallerPolicy

    return CallerPolicy(node=node, kind="consumer", tenants=tenants, actions=actions)


def _validator(*, scopes: dict | None = None) -> IngressValidator:
    policies = (
        {"odoo-k1": _policy()}
        if scopes is None
        else {key_id: _policy(actions=actions) for key_id, actions in scopes.items()}
    )
    return IngressValidator(
        local_node="gate",
        require_signature=True,
        key_resolver=KEYS.get,
        caller_policies=policies,
    )


def _service(**kwargs) -> AdmissionService:
    return AdmissionService(
        local_node="gate", ingress_validator=_validator(**kwargs), registry=_registry()
    )


def test_scoped_key_is_told_exactly_its_granted_actions() -> None:
    receipt = _service().admit(_probe("odoo-k1")).payload

    assert receipt["schema"] == "l9.gate.admission.v1"
    assert receipt["key_id"] == "odoo-k1"
    assert receipt["source_node"] == "odoo"
    assert receipt["scope"] == "restricted"
    assert receipt["scoped_actions"] == ["converge", "match"]
    assert receipt["granted_actions"] == ["converge", "match"]
    assert receipt["routable_actions"] == ["converge", "match", "sync"]


def test_granted_actions_are_limited_to_what_is_registered() -> None:
    service = _service(scopes={"odoo-k1": ("converge", "not-registered")})

    receipt = service.admit(_probe("odoo-k1")).payload

    assert receipt["scoped_actions"] == ["converge", "not-registered"]
    assert receipt["granted_actions"] == ["converge"]


def test_key_missing_from_caller_policy_is_refused() -> None:
    with pytest.raises(IngressAuthorizationError, match="no caller policy"):
        _service().admit(_probe("eie-k1"))


def test_response_is_addressed_back_to_the_caller() -> None:
    response = _service().admit(_probe("odoo-k1"))

    assert response.header.packet_type == "response"
    assert response.address.source_node == "gate"
    assert response.address.destination_node == "odoo"


def test_unknown_key_is_refused() -> None:
    with pytest.raises(IngressValidationError):
        _service().admit(_probe("stranger-k1", key="stranger-secret-0123456789"))


def test_forged_signature_is_refused() -> None:
    with pytest.raises(IngressValidationError):
        _service().admit(_probe("odoo-k1", key="not-the-odoo-secret-0123"))


def test_unsigned_probe_is_refused_even_without_signature_enforcement() -> None:
    validator = IngressValidator(local_node="gate", require_signature=False, dev_mode=True)
    service = AdmissionService(local_node="gate", ingress_validator=validator, registry=_registry())

    with pytest.raises(IngressAuthorizationError):
        service.admit(_probe(None))


def test_probe_must_use_the_admission_action() -> None:
    with pytest.raises(IngressValidationError):
        _service().admit(_probe("odoo-k1", action="converge"))


def test_admission_action_is_not_executable() -> None:
    with pytest.raises(IngressValidationError, match="reserved"):
        _validator().validate(_probe("eie-k1"))


def test_admission_action_cannot_be_registered() -> None:
    with pytest.raises(ValueError, match="reserved"):
        NodeRegistration(
            node_name="rogue",
            internal_url="http://rogue:8000",
            supported_actions=(ADMISSION_ACTION,),
        )


# ── HTTP surface ────────────────────────────────────────────────────────────


@pytest.fixture
def gate(monkeypatch: pytest.MonkeyPatch):
    from constellation_gate.config.settings import GateSettings

    settings = GateSettings(
        environment="local", local_node="gate", signing_key=GATE_KEY, signing_key_id="gate-k1"
    )
    monkeypatch.setattr(deps, "get_gate_settings", lambda: settings)
    monkeypatch.setattr(deps, "get_admission_service", _service)
    return TestClient(create_app())


def test_endpoint_returns_a_gate_signed_receipt(gate: TestClient) -> None:
    response = gate.post("/v1/admission", json=_probe("odoo-k1"))

    assert response.status_code == 200
    packet = TransportPacket.model_validate(response.json())
    assert packet.security.signing_key_id == "gate-k1"
    assert verify_transport_packet_signature(packet, key_resolver={"gate-k1": GATE_KEY}) is True
    assert packet.payload["granted_actions"] == ["converge", "match"]


def test_endpoint_maps_an_unknown_key_to_400(gate: TestClient) -> None:
    response = gate.post(
        "/v1/admission", json=_probe("stranger-k1", key="stranger-secret-0123456789")
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_transport_packet"


def test_endpoint_maps_an_unsigned_probe_to_403(
    monkeypatch: pytest.MonkeyPatch, gate: TestClient
) -> None:
    validator = IngressValidator(local_node="gate", require_signature=False, dev_mode=True)
    monkeypatch.setattr(
        deps,
        "get_admission_service",
        lambda: AdmissionService(
            local_node="gate", ingress_validator=validator, registry=_registry()
        ),
    )

    response = gate.post("/v1/admission", json=_probe(None))

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "action_not_permitted"
