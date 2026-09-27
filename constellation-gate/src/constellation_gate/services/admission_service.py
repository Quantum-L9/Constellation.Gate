from __future__ import annotations

from typing import Any

from constellation_node_sdk.transport.packet import TransportPacket

from constellation_gate.boundary.ingress_validator import IngressValidator
from constellation_gate.boundary.response_factory import ResponseFactory
from constellation_gate.routing.node_registry import NodeRegistry

ADMISSION_SCHEMA = "l9.gate.admission.v1"


class AdmissionService:
    """
    Answer a consumer's admission probe: which actions may this key invoke here?

    Gate is the authority. The probe is validated exactly like an execute
    request, so the key id is proven by its signature, and the answer is Gate's
    own configuration (``L9_KEY_ALLOWED_ACTIONS_JSON``) intersected with what is
    currently registered. Nothing is dispatched and nothing is mutated.
    """

    def __init__(
        self,
        *,
        local_node: str,
        ingress_validator: IngressValidator,
        registry: NodeRegistry,
    ) -> None:
        self._local_node = local_node.strip().lower()
        self._ingress_validator = ingress_validator
        self._registry = registry
        self._responses = ResponseFactory()

    def admit(self, body: dict[str, Any]) -> TransportPacket:
        packet, scope = self._ingress_validator.validate_admission(body)
        routable = sorted(self._registry.all_supported_actions())
        if scope is None:
            granted = routable
        else:
            granted = sorted(set(scope) & set(routable))
        payload: dict[str, Any] = {
            "schema": ADMISSION_SCHEMA,
            "gate_node": self._local_node,
            "key_id": packet.security.signing_key_id,
            "source_node": packet.address.source_node,
            "scope": "unrestricted" if scope is None else "restricted",
            "scoped_actions": None if scope is None else sorted(scope),
            "granted_actions": granted,
            "routable_actions": routable,
        }
        return self._responses.build(
            request_packet=packet,
            source_node=self._local_node,
            payload=payload,
        )
