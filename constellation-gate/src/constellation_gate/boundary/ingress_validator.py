from __future__ import annotations

from collections.abc import Callable
from typing import Any

from constellation_node_sdk.security.validation import validate_transport_packet
from constellation_node_sdk.transport.packet import TransportPacket

from constellation_gate.config.settings import CallerPolicy
from constellation_gate.routing.node_registry import ADMISSION_ACTION

from .routing_policy import validate_node_origin_policy
from .transport_codec import decode_request_body


class IngressValidationError(Exception):
    """Raised when a request fails Gate ingress validation."""


class IngressAuthorizationError(Exception):
    """Raised when a verified caller's key is not scoped to the requested action."""


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
        caller_policies: dict[str, CallerPolicy] | None = None,
        require_caller_policy: bool = False,
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
        self._caller_policies = caller_policies or {}
        self._require_caller_policy = require_caller_policy

    def validate(self, body: dict[str, Any]) -> TransportPacket:
        """
        Decode and validate a strict canonical TransportPacket request.
        """
        packet = self._validate_packet(body, allowed_actions=self._allowed_actions or None)
        if packet.header.action == ADMISSION_ACTION:
            raise IngressValidationError(
                f"{ADMISSION_ACTION!r} is reserved for POST /v1/admission and is not routable"
            )
        self._authorize_action(packet)
        return packet

    def validate_admission(
        self, body: dict[str, Any]
    ) -> tuple[TransportPacket, tuple[str, ...] | None]:
        """
        Validate an admission probe and return it with the caller's action scope.

        The probe passes the same transport validation as an execute request
        (signature, freshness, replay, origin policy), so the key id it carries
        is proven identity. The returned actions are that key's policy. ``None``
        means local/dev has no caller policy configured. A key with no record
        while a policy is in force is refused. The admission action itself is
        not required to appear in the action list. Gate decides; the probe only asks.
        """
        packet = self._validate_packet(body, allowed_actions=None)
        if packet.header.action != ADMISSION_ACTION:
            raise IngressValidationError(f"admission probes must use action {ADMISSION_ACTION!r}")
        if packet.security.signature is None:
            raise IngressAuthorizationError(
                "admission requires a signed packet: an unsigned caller cannot prove its key id"
            )
        policy = self._resolve_caller_policy(packet, check_action=False)
        if policy is None:
            return packet, None
        return packet, policy.actions

    def _validate_packet(
        self, body: dict[str, Any], *, allowed_actions: tuple[str, ...] | None
    ) -> TransportPacket:
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
                allowed_actions=allowed_actions,
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
        except Exception as exc:  # noqa: BLE001
            raise IngressValidationError(str(exc)) from exc
        return packet

    def _authorize_action(self, packet: TransportPacket) -> None:
        # Runs only after validate_transport_packet has verified the signature,
        # so signing_key_id is the caller's proven identity, not a claim.
        self._resolve_caller_policy(packet, check_action=True)

    def _resolve_caller_policy(
        self, packet: TransportPacket, *, check_action: bool
    ) -> CallerPolicy | None:
        """Return the caller's record, or None when local/dev has no policy map.

        A key missing from a configured map is refused. Staging and prod refuse
        a missing record even when the map itself is empty.
        """
        if not self._caller_policies and not self._require_caller_policy:
            return None
        if packet.security.signature is None:
            raise IngressAuthorizationError("unsigned packet refused: caller policy is in force")
        key_id = packet.security.signing_key_id or ""
        policy = self._caller_policies.get(key_id)
        if policy is None:
            msg = f"key {key_id!r} has no caller policy"
            raise IngressAuthorizationError(msg)
        source = packet.address.source_node.strip().lower()
        if source != policy.node:
            msg = f"key {key_id!r} is not permitted to claim source_node {source!r}"
            raise IngressAuthorizationError(msg)
        tenant = packet.tenant.org_id.strip().lower()
        if tenant not in policy.tenants:
            msg = f"key {key_id!r} is not permitted to act for tenant {tenant!r}"
            raise IngressAuthorizationError(msg)
        if check_action and packet.header.action not in policy.actions:
            msg = f"key {key_id!r} is not permitted to invoke action {packet.header.action!r}"
            raise IngressAuthorizationError(msg)
        return policy
