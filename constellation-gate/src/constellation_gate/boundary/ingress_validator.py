from __future__ import annotations

from collections.abc import Callable
from typing import Any

from constellation_node_sdk.security.validation import validate_transport_packet
from constellation_node_sdk.transport.packet import TransportPacket

from .routing_policy import validate_node_origin_policy
from .transport_codec import decode_request_body


class IngressValidationError(Exception):
    """Raised when a request fails Gate ingress validation."""


class IngressValidator:
    """
    Strict Gate ingress validator for canonical TransportPacket requests.
    """

    def __init__(
        self,
        *,
        local_node: str,
        known_nodes_provider: Callable[[], set[str]] | None = None,
        allowed_actions: tuple[str, ...] = (),
        allowed_packet_types: tuple[str, ...] = (
            "request",
            "command",
            "delegation",
            "replay_request",
        ),
        allowed_clock_skew_seconds: int = 30,
        max_packet_bytes: int = 262_144,
        max_hop_depth: int = 64,
        max_delegation_depth: int = 8,
        max_attachments: int = 32,
        max_attachment_size_bytes: int = 10_485_760,
        allowed_attachment_schemes: tuple[str, ...] = (),
        allow_private_attachment_hosts: bool = False,
        require_signature: bool = False,
        key_resolver: Callable[[str | None], str | bytes | None] | None = None,
        required_idempotency_actions: tuple[str, ...] = (),
        replay_enabled: bool = True,
        dev_mode: bool = False,
        verify_hop_signatures: bool = False,
        hop_key_resolver: Callable[[str | None], str | bytes | None] | None = None,
    ) -> None:
        self._local_node = local_node.strip().lower()
        self._known_nodes_provider = known_nodes_provider or (lambda: set())
        self._allowed_actions = allowed_actions
        self._allowed_packet_types = allowed_packet_types
        self._allowed_clock_skew_seconds = allowed_clock_skew_seconds
        self._max_packet_bytes = max_packet_bytes
        self._max_hop_depth = max_hop_depth
        self._max_delegation_depth = max_delegation_depth
        self._max_attachments = max_attachments
        self._max_attachment_size_bytes = max_attachment_size_bytes
        self._allowed_attachment_schemes = allowed_attachment_schemes
        self._allow_private_attachment_hosts = allow_private_attachment_hosts
        self._require_signature = require_signature
        self._key_resolver = key_resolver
        self._required_idempotency_actions = required_idempotency_actions
        self._replay_enabled = replay_enabled
        self._dev_mode = dev_mode
        self._verify_hop_signatures = verify_hop_signatures
        self._hop_key_resolver = hop_key_resolver

    def validate(self, body: dict[str, Any]) -> TransportPacket:
        """
        Decode and validate a strict canonical TransportPacket request.
        """
        try:
            packet = decode_request_body(body)
            validate_transport_packet(
                packet,
                key_resolver=self._key_resolver,
                require_signature=self._require_signature,
                max_packet_bytes=self._max_packet_bytes,
                max_hop_depth=self._max_hop_depth,
                max_delegation_depth=self._max_delegation_depth,
                max_attachments=self._max_attachments,
                max_attachment_size_bytes=self._max_attachment_size_bytes,
                allowed_attachment_schemes=self._allowed_attachment_schemes,
                allow_private_attachment_hosts=self._allow_private_attachment_hosts,
                allowed_clock_skew_seconds=self._allowed_clock_skew_seconds,
                local_node=self._local_node,
                allowed_actions=self._allowed_actions or None,
                allowed_packet_types=self._allowed_packet_types or None,
                required_idempotency_actions=self._required_idempotency_actions or None,
                replay_enabled=self._replay_enabled,
                dev_mode=self._dev_mode,
                verify_hop_signatures=self._verify_hop_signatures,
                hop_key_resolver=self._hop_key_resolver,
            )
            validate_node_origin_policy(
                packet,
                local_node=self._local_node,
                known_nodes=self._known_nodes_provider(),
            )
            return packet
        except Exception as exc:  # noqa: BLE001
            raise IngressValidationError(str(exc)) from exc
