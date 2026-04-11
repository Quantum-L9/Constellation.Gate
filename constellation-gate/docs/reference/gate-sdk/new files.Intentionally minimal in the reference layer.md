# filename: src/constellation_node_sdk/gate/client.py
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from constellation_node_sdk.transport.packet import TransportPacket, create_transport_packet


class GateClient:
    """
    Canonical SDK client for sending TransportPacket traffic to Gate.

    Architectural rules:
    - all outbound work goes to Gate
    - no node-to-node direct addressing
    - Gate remains sole routing authority
    """

    def __init__(
        self,
        gate_url: str,
        *,
        source_node: str = "client",
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        normalized_gate_url = gate_url.strip().rstrip("/")
        if not normalized_gate_url:
            raise ValueError("gate_url must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")

        self._gate_url = normalized_gate_url
        self._source_node = source_node.strip().lower()
        self._timeout_seconds = timeout_seconds
        self._client = client

    @property
    def execute_url(self) -> str:
        return f"{self._gate_url}/v1/execute"

    async def send_to_gate(self, packet: TransportPacket) -> TransportPacket:
        """
        Send an already-constructed TransportPacket to Gate.

        The packet must target Gate. This client refuses peer-targeted packets.
        """
        if packet.address.destination_node != "gate":
            raise ValueError("GateClient only sends packets whose destination_node is 'gate'")

        if self._client is not None:
            response = await self._client.post(
                self.execute_url,
                json=packet.model_dump_json_dict(),
                headers={"Content-Type": "application/json"},
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("Gate response must be a JSON object")
            return TransportPacket.model_validate(body)

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.post(
                self.execute_url,
                json=packet.model_dump_json_dict(),
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("Gate response must be a JSON object")
            return TransportPacket.model_validate(body)

    async def execute(
        self,
        *,
        action: str,
        payload: Mapping[str, Any],
        tenant: str | Mapping[str, Any],
        idempotency_key: str | None = None,
        timeout_ms: int = 30_000,
        priority: int = 2,
        reply_to: str | None = None,
        packet_type: str = "request",
    ) -> TransportPacket:
        """
        High-level convenience entrypoint for Gate-bound execution.
        """
        packet = create_transport_packet(
            action=action,
            payload=dict(payload),
            tenant=tenant,
            destination_node="gate",
            source_node=self._source_node,
            reply_to=reply_to or self._source_node,
            idempotency_key=idempotency_key,
            timeout_ms=timeout_ms,
            priority=priority,
            packet_type=packet_type,
        )
        return await self.send_to_gate(packet)

# filename: src/constellation_node_sdk/transport/packet.py
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def _sha256_hex(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


class TransportHeader(BaseModel):
    model_config = ConfigDict(extra="forbid")

    packet_id: UUID = Field(default_factory=uuid4)
    packet_type: str = "request"
    action: str
    priority: int = Field(default=2, ge=0, le=3)
    created_at: datetime = Field(default_factory=_utc_now)
    expires_at: datetime | None = None
    timeout_ms: int = Field(default=30_000, ge=1)
    schema_version: str = "1.0"
    idempotency_key: str | None = None
    trace_id: str | None = None
    correlation_id: str | None = None
    causation_id: UUID | None = None
    retry_count: int = Field(default=0, ge=0)
    replay_mode: bool = False
    not_before: datetime | None = None

    @field_validator("action")
    @classmethod
    def _validate_action(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("action must not be blank")
        return normalized


class TransportAddress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_node: str
    destination_node: str
    reply_to: str

    @field_validator("source_node", "destination_node", "reply_to")
    @classmethod
    def _normalize_node_name(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("node name must not be blank")
        return normalized


class TenantContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor: str
    on_behalf_of: str
    originator: str
    org_id: str
    user_id: str | None = None

    @classmethod
    def from_value(cls, tenant: str | Mapping[str, Any]) -> "TenantContext":
        if isinstance(tenant, str):
            normalized = tenant.strip()
            if not normalized:
                raise ValueError("tenant must not be blank")
            return cls(
                actor=normalized,
                on_behalf_of=normalized,
                originator=normalized,
                org_id=normalized,
                user_id=None,
            )

        payload = dict(tenant)
        if "org_id" not in payload:
            raise ValueError("tenant mapping must include org_id")
        return cls.model_validate(payload)


class SecurityEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payload_hash: str
    transport_hash: str
    signature: str | None = None
    signature_algorithm: str | None = None
    signing_key_id: str | None = None
    classification: str = "internal"
    encryption_status: str = "plaintext"
    pii_fields: tuple[str, ...] = ()


class GovernanceEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: str
    compliance_tags: tuple[str, ...] = ()
    retention_days: int = Field(default=90, ge=0)
    redaction_applied: bool = False
    audit_required: bool = False
    data_subject_id: str | None = None


class RoutingProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    origin_kind: str
    requested_action: str
    resolved_by_gate: bool
    original_source_node: str | None = None

    @field_validator("origin_kind")
    @classmethod
    def _validate_origin_kind(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"client", "node", "gate"}:
            raise ValueError("origin_kind must be one of: client, node, gate")
        return normalized

    @field_validator("requested_action")
    @classmethod
    def _validate_requested_action(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("requested_action must not be blank")
        return normalized


class DelegationLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delegator: str
    delegatee: str
    scope: tuple[str, ...]
    granted_at: datetime
    expires_at: datetime | None = None
    constraints: dict[str, Any] | None = None
    proof: str | None = None


class TransportHop(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hop_id: UUID = Field(default_factory=uuid4)
    packet_id: UUID
    node: str
    action: str
    direction: str
    status: str
    timestamp: datetime = Field(default_factory=_utc_now)
    attempt: int | None = None
    target_node: str | None = None
    duration_ms: int | None = None
    queue_ms: int | None = None
    network_ms: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    previous_hop_hash: str | None = None
    hop_hash: str
    hop_signature: str | None = None
    hop_signature_algorithm: str | None = None
    hop_signing_key_id: str | None = None


class TransportLineage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_id: UUID | None = None
    root_id: UUID
    generation: int = Field(default=0, ge=0)


class Attachment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attachment_id: UUID = Field(default_factory=uuid4)
    media_type: str
    uri: str
    content_hash: str
    encrypted: bool = False
    size_bytes: int = Field(ge=0)


class TransportPacket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    header: TransportHeader
    address: TransportAddress
    tenant: TenantContext
    payload: dict[str, Any]
    security: SecurityEnvelope
    governance: GovernanceEnvelope
    provenance: RoutingProvenance
    delegation_chain: tuple[DelegationLink, ...] = ()
    hop_trace: tuple[TransportHop, ...] = ()
    lineage: TransportLineage
    attachments: tuple[Attachment, ...] = ()

    def model_dump_json_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def _transport_core_dict(
        self,
        *,
        header: TransportHeader | None = None,
        address: TransportAddress | None = None,
        payload: dict[str, Any] | None = None,
        provenance: RoutingProvenance | None = None,
        lineage: TransportLineage | None = None,
        delegation_chain: tuple[DelegationLink, ...] | None = None,
        attachments: tuple[Attachment, ...] | None = None,
        payload_hash: str | None = None,
    ) -> dict[str, Any]:
        resolved_header = header or self.header
        resolved_address = address or self.address
        resolved_payload = payload if payload is not None else self.payload
        resolved_provenance = provenance or self.provenance
        resolved_lineage = lineage or self.lineage
        resolved_delegation_chain = delegation_chain if delegation_chain is not None else self.delegation_chain
        resolved_attachments = attachments if attachments is not None else self.attachments
        resolved_payload_hash = payload_hash or self.security.payload_hash

        return {
            "header": resolved_header.model_dump(mode="json"),
            "address": resolved_address.model_dump(mode="json"),
            "tenant": self.tenant.model_dump(mode="json"),
            "payload": resolved_payload,
            "governance": self.governance.model_dump(mode="json"),
            "provenance": resolved_provenance.model_dump(mode="json"),
            "delegation_chain": [link.model_dump(mode="json") for link in resolved_delegation_chain],
            "lineage": resolved_lineage.model_dump(mode="json"),
            "attachments": [attachment.model_dump(mode="json") for attachment in resolved_attachments],
            "payload_hash": resolved_payload_hash,
        }

    def derive(
        self,
        *,
        packet_type: str | None = None,
        action: str | None = None,
        source_node: str | None = None,
        destination_node: str | None = None,
        reply_to: str | None = None,
        payload: dict[str, Any] | None = None,
        provenance: RoutingProvenance | None = None,
        idempotency_key: str | None = None,
        timeout_ms: int | None = None,
    ) -> "TransportPacket":
        derived_header = self.header.model_copy(
            update={
                "packet_id": uuid4(),
                "packet_type": self.header.packet_type if packet_type is None else packet_type,
                "action": self.header.action if action is None else action,
                "created_at": _utc_now(),
                "idempotency_key": idempotency_key,
                "causation_id": self.header.packet_id,
                "retry_count": 0,
                "timeout_ms": self.header.timeout_ms if timeout_ms is None else timeout_ms,
            }
        )
        derived_address = self.address.model_copy(
            update={
                "source_node": self.address.source_node if source_node is None else source_node,
                "destination_node": self.address.destination_node if destination_node is None else destination_node,
                "reply_to": self.address.reply_to if reply_to is None else reply_to,
            }
        )
        derived_payload = dict(self.payload if payload is None else payload)
        derived_provenance = self.provenance if provenance is None else provenance
        derived_lineage = TransportLineage(
            parent_id=self.header.packet_id,
            root_id=self.lineage.root_id,
            generation=self.lineage.generation + 1,
        )

        payload_hash = _sha256_hex(derived_payload)
        transport_hash = _sha256_hex(
            self._transport_core_dict(
                header=derived_header,
                address=derived_address,
                payload=derived_payload,
                provenance=derived_provenance,
                lineage=derived_lineage,
                payload_hash=payload_hash,
            )
        )

        return TransportPacket(
            header=derived_header,
            address=derived_address,
            tenant=self.tenant,
            payload=derived_payload,
            security=self.security.model_copy(
                update={
                    "payload_hash": payload_hash,
                    "transport_hash": transport_hash,
                    "signature": None,
                    "signature_algorithm": None,
                    "signing_key_id": None,
                }
            ),
            governance=self.governance,
            provenance=derived_provenance,
            delegation_chain=self.delegation_chain,
            hop_trace=self.hop_trace,
            lineage=derived_lineage,
            attachments=self.attachments,
        )

    def with_hop(self, hop: TransportHop) -> "TransportPacket":
        return self.model_copy(update={"hop_trace": self.hop_trace + (hop,)})


def create_transport_packet(
    *,
    action: str,
    payload: Mapping[str, Any],
    tenant: str | Mapping[str, Any],
    destination_node: str,
    source_node: str,
    reply_to: str,
    packet_type: str = "request",
    idempotency_key: str | None = None,
    timeout_ms: int = 30_000,
    priority: int = 2,
    classification: str = "internal",
    encryption_status: str = "plaintext",
    compliance_tags: tuple[str, ...] = (),
    audit_required: bool = False,
    provenance: RoutingProvenance | None = None,
) -> TransportPacket:
    """
    Canonical packet factory for the SDK.

    Rules:
    - source and destination must be explicit
    - destination is usually 'gate' for client and node-origin packets
    - provenance defaults are derived from source_node
    """
    normalized_payload = dict(payload)
    tenant_context = TenantContext.from_value(tenant)

    header = TransportHeader(
        packet_type=packet_type,
        action=action,
        priority=priority,
        timeout_ms=timeout_ms,
        idempotency_key=idempotency_key,
    )
    address = TransportAddress(
        source_node=source_node,
        destination_node=destination_node,
        reply_to=reply_to,
    )

    if provenance is None:
        origin_kind = "client" if address.source_node == "client" else "node"
        provenance = RoutingProvenance(
            origin_kind=origin_kind,
            requested_action=header.action,
            resolved_by_gate=False,
            original_source_node=None if origin_kind == "client" else address.source_node,
        )

    payload_hash = _sha256_hex(normalized_payload)
    lineage = TransportLineage(
        parent_id=None,
        root_id=header.packet_id,
        generation=0,
    )
    governance = GovernanceEnvelope(
        intent=header.action,
        compliance_tags=compliance_tags,
        audit_required=audit_required,
    )

    transport_hash = _sha256_hex(
        {
            "header": header.model_dump(mode="json"),
            "address": address.model_dump(mode="json"),
            "tenant": tenant_context.model_dump(mode="json"),
            "payload": normalized_payload,
            "governance": governance.model_dump(mode="json"),
            "provenance": provenance.model_dump(mode="json"),
            "delegation_chain": [],
            "lineage": lineage.model_dump(mode="json"),
            "attachments": [],
            "payload_hash": payload_hash,
        }
    )

    return TransportPacket(
        header=header,
        address=address,
        tenant=tenant_context,
        payload=normalized_payload,
        security=SecurityEnvelope(
            payload_hash=payload_hash,
            transport_hash=transport_hash,
            classification=classification,
            encryption_status=encryption_status,
        ),
        governance=governance,
        provenance=provenance,
        lineage=lineage,
    )

# filename: src/constellation_node_sdk/runtime/node_runtime.py
from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from constellation_node_sdk.gate.client import GateClient
from constellation_node_sdk.transport.packet import (
    RoutingProvenance,
    TransportPacket,
    create_transport_packet,
)

Handler = Callable[..., Awaitable[dict[str, Any] | TransportPacket] | dict[str, Any] | TransportPacket]


class NodeRuntime:
    """
    Minimal production-aligned node runtime scaffold.

    Guarantees:
    - accepts canonical TransportPacket only
    - executes local handlers only
    - never routes directly to peer nodes
    - uses GateClient for follow-up work
    """

    def __init__(
        self,
        *,
        node_name: str,
        gate_url: str,
        service_name: str | None = None,
        version: str = "1.0.0",
    ) -> None:
        normalized_node_name = node_name.strip().lower()
        if not normalized_node_name:
            raise ValueError("node_name must not be blank")

        self.node_name = normalized_node_name
        self.service_name = service_name or normalized_node_name
        self.version = version
        self.gate_client = GateClient(gate_url, source_node=normalized_node_name)
        self._handlers: dict[str, Handler] = {}

    def handler(self, action: str) -> Callable[[Handler], Handler]:
        normalized_action = action.strip().lower()
        if not normalized_action:
            raise ValueError("action must not be blank")

        def decorator(func: Handler) -> Handler:
            self._handlers[normalized_action] = func
            return func

        return decorator

    def get_handler(self, action: str) -> Handler | None:
        return self._handlers.get(action.strip().lower())

    async def send_via_gate(
        self,
        *,
        parent: TransportPacket,
        action: str,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
        timeout_ms: int | None = None,
    ) -> TransportPacket:
        """
        Canonical node follow-up path:
        node -> gate -> resolved worker
        """
        child = parent.derive(
            action=action,
            source_node=self.node_name,
            destination_node="gate",
            reply_to=self.node_name,
            payload=payload,
            idempotency_key=idempotency_key,
            timeout_ms=parent.header.timeout_ms if timeout_ms is None else timeout_ms,
            provenance=RoutingProvenance(
                origin_kind="node",
                requested_action=action,
                resolved_by_gate=False,
                original_source_node=self.node_name,
            ),
        )
        return await self.gate_client.send_to_gate(child)

    async def _invoke_handler(self, handler: Handler, packet: TransportPacket) -> dict[str, Any] | TransportPacket:
        parameters = list(inspect.signature(handler).parameters.values())

        if len(parameters) == 1:
            result = handler(packet)
        elif len(parameters) == 2:
            result = handler(packet.tenant.org_id, packet.payload)
        elif len(parameters) == 3:
            result = handler(packet.tenant.org_id, packet.payload, packet)
        else:
            raise TypeError("handler must accept (packet) or (tenant, payload) or (tenant, payload, packet)")

        if inspect.isawaitable(result):
            return await result
        return result

    def _response_packet_from_result(
        self,
        *,
        request_packet: TransportPacket,
        result: dict[str, Any] | TransportPacket,
    ) -> TransportPacket:
        if isinstance(result, TransportPacket):
            return result

        return request_packet.derive(
            packet_type="response",
            source_node=self.node_name,
            destination_node=request_packet.address.reply_to,
            reply_to=self.node_name,
            payload=result,
            provenance=RoutingProvenance(
                origin_kind="node",
                requested_action=request_packet.header.action,
                resolved_by_gate=False,
                original_source_node=self.node_name,
            ),
        )

    def _failure_packet(self, *, request_packet: TransportPacket, exc: Exception) -> TransportPacket:
        return request_packet.derive(
            packet_type="failure",
            source_node=self.node_name,
            destination_node=request_packet.address.reply_to,
            reply_to=self.node_name,
            payload={
                "status": "failed",
                "error": exc.__class__.__name__,
                "message": str(exc),
            },
            provenance=RoutingProvenance(
                origin_kind="node",
                requested_action=request_packet.header.action,
                resolved_by_gate=False,
                original_source_node=self.node_name,
            ),
        )

    def create_app(self) -> FastAPI:
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            app.state.runtime = self
            yield

        app = FastAPI(title=self.service_name, version=self.version, lifespan=lifespan)

        @app.get("/v1/health")
        async def health() -> dict[str, Any]:
            return {
                "status": "healthy",
                "service_name": self.service_name,
                "node_name": self.node_name,
                "version": self.version,
            }

        @app.post("/v1/execute")
        async def execute(request: Request) -> JSONResponse:
            try:
                body = await request.json()
                if not isinstance(body, dict):
                    raise ValueError("request body must be a JSON object")
                packet = TransportPacket.model_validate(body)

                if packet.address.destination_node != self.node_name:
                    raise ValueError("packet destination does not match this node")

                handler = self.get_handler(packet.header.action)
                if handler is None:
                    raise LookupError(f"no handler registered for action: {packet.header.action}")

                result = await self._invoke_handler(handler, packet)
                response_packet = self._response_packet_from_result(
                    request_packet=packet,
                    result=result,
                )
                return JSONResponse(content=response_packet.model_dump_json_dict())

            except LookupError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except Exception as exc:  # noqa: BLE001
                if "packet" in locals():
                    failure_packet = self._failure_packet(request_packet=packet, exc=exc)
                    return JSONResponse(content=failure_packet.model_dump_json_dict(), status_code=200)
                raise HTTPException(status_code=500, detail="internal server error") from exc

        return app


# Example reference usage:
runtime = NodeRuntime(node_name="score", gate_url="http://gate:9000")


@runtime.handler("score")
async def handle_score(_tenant: str, payload: dict[str, Any], packet: TransportPacket) -> dict[str, Any]:
    entity_id = payload["entity_id"]
    return {
        "status": "completed",
        "entity_id": entity_id,
        "score": 91,
        "lineage_root_id": str(packet.lineage.root_id),
    }


app = runtime.create_app()

# filename: tests/gate/test_reference_gate_client.py
from __future__ import annotations

import httpx
import pytest

from constellation_node_sdk.gate.client import GateClient
from constellation_node_sdk.transport.packet import TransportPacket, create_transport_packet


class CapturingTransport(httpx.AsyncBaseTransport):
    def __init__(self, response_packet: TransportPacket) -> None:
        self.requests: list[httpx.Request] = []
        self.response_packet = response_packet

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(
            status_code=200,
            json=self.response_packet.model_dump_json_dict(),
            request=request,
        )


@pytest.mark.asyncio
async def test_gate_client_execute_builds_gate_bound_transport_packet() -> None:
    response_packet = create_transport_packet(
        action="score",
        payload={"status": "completed", "score": 91},
        tenant="tenant-a",
        destination_node="client",
        source_node="gate",
        reply_to="gate",
        packet_type="response",
    )
    transport = CapturingTransport(response_packet)
    client = httpx.AsyncClient(transport=transport)
    gate_client = GateClient(
        "http://gate:9000",
        source_node="client",
        client=client,
    )

    result = await gate_client.execute(
        action="score",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        idempotency_key="abc-123",
        timeout_ms=15_000,
    )

    assert result.payload["score"] == 91
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert str(request.url) == "http://gate:9000/v1/execute"

    sent = TransportPacket.model_validate(request.content and request.read().decode() and request.json() if False else __import__("json").loads(request.content.decode()))
    assert sent.header.action == "score"
    assert sent.header.idempotency_key == "abc-123"
    assert sent.address.source_node == "client"
    assert sent.address.destination_node == "gate"
    assert sent.address.reply_to == "client"
    assert sent.provenance.origin_kind == "client"
    assert sent.provenance.resolved_by_gate is False

    await client.aclose()


@pytest.mark.asyncio
async def test_gate_client_send_to_gate_rejects_non_gate_destination() -> None:
    packet = create_transport_packet(
        action="score",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="score",
        source_node="orchestrator",
        reply_to="orchestrator",
    )
    gate_client = GateClient("http://gate:9000", source_node="orchestrator")

    with pytest.raises(ValueError, match="destination_node is 'gate'"):
        await gate_client.send_to_gate(packet)

# filename: tests/transport/test_reference_transport_packet.py
from __future__ import annotations

from constellation_node_sdk.transport.packet import RoutingProvenance, TransportPacket, create_transport_packet


def test_create_transport_packet_defaults_align_with_gate_semantics() -> None:
    packet = create_transport_packet(
        action="score",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
    )

    assert packet.header.packet_type == "request"
    assert packet.header.action == "score"
    assert packet.address.source_node == "client"
    assert packet.address.destination_node == "gate"
    assert packet.address.reply_to == "client"
    assert packet.provenance.origin_kind == "client"
    assert packet.provenance.requested_action == "score"
    assert packet.provenance.resolved_by_gate is False
    assert packet.lineage.parent_id is None
    assert packet.lineage.root_id == packet.header.packet_id
    assert packet.lineage.generation == 0
    assert packet.security.payload_hash
    assert packet.security.transport_hash


def test_create_transport_packet_node_origin_defaults_to_node_provenance() -> None:
    packet = create_transport_packet(
        action="enrich",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="orchestrator",
        reply_to="orchestrator",
    )

    assert packet.provenance.origin_kind == "node"
    assert packet.provenance.original_source_node == "orchestrator"
    assert packet.provenance.resolved_by_gate is False


def test_transport_packet_derive_creates_child_packet_and_preserves_root() -> None:
    parent = create_transport_packet(
        action="score",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="gate",
        source_node="client",
        reply_to="client",
        idempotency_key="orig-key",
    )

    child = parent.derive(
        packet_type="response",
        source_node="gate",
        destination_node="client",
        reply_to="gate",
        payload={"status": "completed", "score": 91},
        provenance=RoutingProvenance(
            origin_kind="gate",
            requested_action="score",
            resolved_by_gate=True,
            original_source_node="client",
        ),
        idempotency_key=None,
    )

    assert child.header.packet_id != parent.header.packet_id
    assert child.header.causation_id == parent.header.packet_id
    assert child.header.packet_type == "response"
    assert child.address.source_node == "gate"
    assert child.address.destination_node == "client"
    assert child.lineage.parent_id == parent.header.packet_id
    assert child.lineage.root_id == parent.lineage.root_id
    assert child.lineage.generation == parent.lineage.generation + 1
    assert child.payload["score"] == 91
    assert child.provenance.origin_kind == "gate"
    assert child.security.payload_hash != parent.security.payload_hash
    assert child.security.transport_hash != parent.security.transport_hash

# filename: tests/runtime/test_reference_node_runtime_send_via_gate.py
from __future__ import annotations

import httpx
import pytest

from constellation_node_sdk.runtime.node_runtime import NodeRuntime
from constellation_node_sdk.transport.packet import TransportPacket, create_transport_packet


class CapturingTransport(httpx.AsyncBaseTransport):
    def __init__(self, response_packet: TransportPacket) -> None:
        self.requests: list[httpx.Request] = []
        self.response_packet = response_packet

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(
            status_code=200,
            json=self.response_packet.model_dump_json_dict(),
            request=request,
        )


@pytest.mark.asyncio
async def test_node_runtime_send_via_gate_derives_gate_bound_node_origin_packet() -> None:
    parent = create_transport_packet(
        action="full_pipeline",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="orchestrator",
        source_node="gate",
        reply_to="gate",
    )
    response_packet = create_transport_packet(
        action="score",
        payload={"status": "completed", "score": 91},
        tenant="tenant-a",
        destination_node="orchestrator",
        source_node="gate",
        reply_to="gate",
        packet_type="response",
    )
    transport = CapturingTransport(response_packet)
    client = httpx.AsyncClient(transport=transport)

    runtime = NodeRuntime(node_name="orchestrator", gate_url="http://gate:9000")
    runtime.gate_client = runtime.gate_client.__class__(
        "http://gate:9000",
        source_node="orchestrator",
        client=client,
    )

    result = await runtime.send_via_gate(
        parent=parent,
        action="score",
        payload={"entity_id": "42", "industry": "fintech"},
        idempotency_key="child-1",
    )

    assert result.payload["score"] == 91
    assert len(transport.requests) == 1

    sent = TransportPacket.model_validate(__import__("json").loads(transport.requests[0].content.decode()))
    assert sent.header.action == "score"
    assert sent.header.idempotency_key == "child-1"
    assert sent.address.source_node == "orchestrator"
    assert sent.address.destination_node == "gate"
    assert sent.address.reply_to == "orchestrator"
    assert sent.lineage.parent_id == parent.header.packet_id
    assert sent.lineage.root_id == parent.lineage.root_id
    assert sent.lineage.generation == parent.lineage.generation + 1
    assert sent.provenance.origin_kind == "node"
    assert sent.provenance.resolved_by_gate is False
    assert sent.provenance.original_source_node == "orchestrator"

    await client.aclose()

# filename: tests/runtime/test_reference_node_runtime_app.py
from __future__ import annotations

from fastapi.testclient import TestClient

from constellation_node_sdk.runtime.node_runtime import NodeRuntime
from constellation_node_sdk.transport.packet import create_transport_packet


def test_node_runtime_app_executes_registered_handler_and_returns_transport_packet() -> None:
    runtime = NodeRuntime(node_name="score", gate_url="http://gate:9000")

    @runtime.handler("score")
    async def handle_score(_tenant: str, payload: dict, packet) -> dict:
        return {
            "status": "completed",
            "entity_id": payload["entity_id"],
            "score": 91,
            "root_id": str(packet.lineage.root_id),
        }

    app = runtime.create_app()

    request_packet = create_transport_packet(
        action="score",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="score",
        source_node="gate",
        reply_to="gate",
    )

    with TestClient(app) as client:
        health = client.get("/v1/health")
        assert health.status_code == 200
        assert health.json()["node_name"] == "score"

        response = client.post("/v1/execute", json=request_packet.model_dump_json_dict())

    assert response.status_code == 200
    body = response.json()
    assert body["header"]["packet_type"] == "response"
    assert body["address"]["source_node"] == "score"
    assert body["address"]["destination_node"] == "gate"
    assert body["payload"]["status"] == "completed"
    assert body["payload"]["score"] == 91


def test_node_runtime_app_rejects_wrong_destination_and_missing_handler() -> None:
    runtime = NodeRuntime(node_name="score", gate_url="http://gate:9000")
    app = runtime.create_app()

    wrong_destination_packet = create_transport_packet(
        action="score",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="other-node",
        source_node="gate",
        reply_to="gate",
    )
    missing_handler_packet = create_transport_packet(
        action="unknown",
        payload={"entity_id": "42"},
        tenant="tenant-a",
        destination_node="score",
        source_node="gate",
        reply_to="gate",
    )

    with TestClient(app) as client:
        wrong_destination = client.post("/v1/execute", json=wrong_destination_packet.model_dump_json_dict())
        missing_handler = client.post("/v1/execute", json=missing_handler_packet.model_dump_json_dict())

    assert wrong_destination.status_code == 400
    assert "destination" in wrong_destination.json()["detail"]
    assert missing_handler.status_code == 404
    assert "no handler registered" in missing_handler.json()["detail"]

    # filename: src/constellation_node_sdk/gate/client.py
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from constellation_node_sdk.transport.packet import TransportPacket, create_transport_packet


class GateClient:
    """
    Canonical SDK client for sending TransportPacket traffic to Gate.

    Rules:
    - all outbound work goes to Gate
    - no node-to-node direct addressing
    - Gate remains sole routing authority
    """

    def __init__(
        self,
        gate_url: str,
        *,
        source_node: str = "client",
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        normalized_gate_url = gate_url.strip().rstrip("/")
        normalized_source_node = source_node.strip().lower()

        if not normalized_gate_url:
            raise ValueError("gate_url must not be empty")
        if not normalized_source_node:
            raise ValueError("source_node must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")

        self._gate_url = normalized_gate_url
        self._source_node = normalized_source_node
        self._timeout_seconds = timeout_seconds
        self._client = client

    @property
    def execute_url(self) -> str:
        return f"{self._gate_url}/v1/execute"

    async def send_to_gate(self, packet: TransportPacket) -> TransportPacket:
        """
        Send an already-constructed TransportPacket to Gate.

        The packet must target Gate. This client refuses peer-targeted packets.
        """
        if packet.address.destination_node != "gate":
            raise ValueError("GateClient only sends packets whose destination_node is 'gate'")

        body = packet.model_dump_json_dict()

        if self._client is not None:
            response = await self._client.post(
                self.execute_url,
                json=body,
                headers={"Content-Type": "application/json"},
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Gate response must be a JSON object")
            return TransportPacket.model_validate(payload)

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.post(
                self.execute_url,
                json=body,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Gate response must be a JSON object")
            return TransportPacket.model_validate(payload)

    async def execute(
        self,
        *,
        action: str,
        payload: Mapping[str, Any],
        tenant: str | Mapping[str, Any],
        idempotency_key: str | None = None,
        timeout_ms: int = 30_000,
        priority: int = 2,
        reply_to: str | None = None,
        packet_type: str = "request",
    ) -> TransportPacket:
        """
        High-level convenience entrypoint for Gate-bound execution.
        """
        packet = create_transport_packet(
            action=action,
            payload=dict(payload),
            tenant=tenant,
            destination_node="gate",
            source_node=self._source_node,
            reply_to=reply_to or self._source_node,
            idempotency_key=idempotency_key,
            timeout_ms=timeout_ms,
            priority=priority,
            packet_type=packet_type,
        )
        return await self.send_to_gate(packet)

# filename: src/constellation_node_sdk/transport/packet.py
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def _sha256_hex(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


class TransportHeader(BaseModel):
    model_config = ConfigDict(extra="forbid")

    packet_id: UUID = Field(default_factory=uuid4)
    packet_type: str = "request"
    action: str
    priority: int = Field(default=2, ge=0, le=3)
    created_at: datetime = Field(default_factory=_utc_now)
    expires_at: datetime | None = None
    timeout_ms: int | None = Field(default=30_000, ge=1)
    schema_version: str = "1.0"
    idempotency_key: str | None = None
    trace_id: str | None = None
    correlation_id: str | None = None
    causation_id: UUID | None = None
    retry_count: int = Field(default=0, ge=0)
    replay_mode: bool = False
    not_before: datetime | None = None

    @field_validator("action")
    @classmethod
    def _validate_action(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("action must not be blank")
        return normalized

    @field_validator("packet_type")
    @classmethod
    def _validate_packet_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("packet_type must not be blank")
        return normalized


class TransportAddress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_node: str
    destination_node: str
    reply_to: str

    @field_validator("source_node", "destination_node", "reply_to")
    @classmethod
    def _normalize_node_name(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("node name must not be blank")
        return normalized


class TenantContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor: str
    on_behalf_of: str
    originator: str
    org_id: str
    user_id: str | None = None

    @field_validator("actor", "on_behalf_of", "originator", "org_id")
    @classmethod
    def _normalize_required_fields(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("tenant fields must not be blank")
        return normalized

    @field_validator("user_id")
    @classmethod
    def _normalize_user_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @classmethod
    def from_value(cls, tenant: str | Mapping[str, Any]) -> "TenantContext":
        if isinstance(tenant, str):
            normalized = tenant.strip()
            if not normalized:
                raise ValueError("tenant must not be blank")
            return cls(
                actor=normalized,
                on_behalf_of=normalized,
                originator=normalized,
                org_id=normalized,
                user_id=None,
            )

        payload = dict(tenant)
        if "org_id" not in payload:
            raise ValueError("tenant mapping must include org_id")
        return cls.model_validate(payload)


class SecurityEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payload_hash: str
    transport_hash: str
    signature: str | None = None
    signature_algorithm: str | None = None
    signing_key_id: str | None = None
    classification: str = "internal"
    encryption_status: str = "plaintext"
    pii_fields: tuple[str, ...] = ()

    @field_validator("classification")
    @classmethod
    def _validate_classification(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"public", "internal", "confidential", "restricted"}:
            raise ValueError("invalid classification")
        return normalized

    @field_validator("encryption_status")
    @classmethod
    def _validate_encryption_status(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"plaintext", "encrypted", "envelope_only"}:
            raise ValueError("invalid encryption_status")
        return normalized


class GovernanceEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: str
    compliance_tags: tuple[str, ...] = ()
    retention_days: int = Field(default=90, ge=0)
    redaction_applied: bool = False
    audit_required: bool = False
    data_subject_id: str | None = None

    @field_validator("intent")
    @classmethod
    def _normalize_intent(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("intent must not be blank")
        return normalized


class RoutingProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    origin_kind: str
    requested_action: str
    resolved_by_gate: bool
    original_source_node: str | None = None

    @field_validator("origin_kind")
    @classmethod
    def _validate_origin_kind(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"client", "node", "gate"}:
            raise ValueError("origin_kind must be one of: client, node, gate")
        return normalized

    @field_validator("requested_action")
    @classmethod
    def _validate_requested_action(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("requested_action must not be blank")
        return normalized

    @field_validator("original_source_node")
    @classmethod
    def _normalize_original_source_node(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        return normalized or None


class DelegationLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delegator: str
    delegatee: str
    scope: tuple[str, ...]
    granted_at: datetime
    expires_at: datetime | None = None
    constraints: dict[str, Any] | None = None
    proof: str | None = None


class TransportHop(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hop_id: UUID = Field(default_factory=uuid4)
    packet_id: UUID
    node: str
    action: str
    direction: str
    status: str
    timestamp: datetime = Field(default_factory=_utc_now)
    attempt: int | None = None
    target_node: str | None = None
    duration_ms: int | None = None
    queue_ms: int | None = None
    network_ms: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    previous_hop_hash: str | None = None
    hop_hash: str
    hop_signature: str | None = None
    hop_signature_algorithm: str | None = None
    hop_signing_key_id: str | None = None


class TransportLineage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_id: UUID | None = None
    root_id: UUID
    generation: int = Field(default=0, ge=0)


class Attachment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attachment_id: UUID = Field(default_factory=uuid4)
    media_type: str
    uri: str
    content_hash: str
    encrypted: bool = False
    size_bytes: int = Field(ge=0)


class TransportPacket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    header: TransportHeader
    address: TransportAddress
    tenant: TenantContext
    payload: dict[str, Any]
    security: SecurityEnvelope
    governance: GovernanceEnvelope
    provenance: RoutingProvenance
    delegation_chain: tuple[DelegationLink, ...] = ()
    hop_trace: tuple[TransportHop, ...] = ()
    lineage: TransportLineage
    attachments: tuple[Attachment, ...] = ()

    def model_dump_json_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def _transport_core_dict(
        self,
        *,
        header: TransportHeader | None = None,
        address: TransportAddress | None = None,
        payload: dict[str, Any] | None = None,
        provenance: RoutingProvenance | None = None,
        lineage: TransportLineage | None = None,
        delegation_chain: tuple[DelegationLink, ...] | None = None,
        attachments: tuple[Attachment, ...] | None = None,
        payload_hash: str | None = None,
    ) -> dict[str, Any]:
        resolved_header = header or self.header
        resolved_address = address or self.address
        resolved_payload = payload if payload is not None else self.payload
        resolved_provenance = provenance or self.provenance
        resolved_lineage = lineage or self.lineage
        resolved_delegation_chain = delegation_chain if delegation_chain is not None else self.delegation_chain
        resolved_attachments = attachments if attachments is not None else self.attachments
        resolved_payload_hash = payload_hash or self.security.payload_hash

        return {
            "header": resolved_header.model_dump(mode="json"),
            "address": resolved_address.model_dump(mode="json"),
            "tenant": self.tenant.model_dump(mode="json"),
            "payload": resolved_payload,
            "governance": self.governance.model_dump(mode="json"),
            "provenance": resolved_provenance.model_dump(mode="json"),
            "delegation_chain": [link.model_dump(mode="json") for link in resolved_delegation_chain],
            "lineage": resolved_lineage.model_dump(mode="json"),
            "attachments": [attachment.model_dump(mode="json") for attachment in resolved_attachments],
            "payload_hash": resolved_payload_hash,
        }

    def derive(
        self,
        *,
        packet_type: str | None = None,
        action: str | None = None,
        source_node: str | None = None,
        destination_node: str | None = None,
        reply_to: str | None = None,
        payload: dict[str, Any] | None = None,
        provenance: RoutingProvenance | None = None,
        idempotency_key: str | None = None,
        timeout_ms: int | None = None,
    ) -> "TransportPacket":
        next_packet_type = self.header.packet_type if packet_type is None else packet_type
        next_action = self.header.action if action is None else action

        derived_header = self.header.model_copy(
            update={
                "packet_id": uuid4(),
                "packet_type": next_packet_type,
                "action": next_action,
                "created_at": _utc_now(),
                "idempotency_key": idempotency_key,
                "causation_id": self.header.packet_id,
                "retry_count": 0,
                "timeout_ms": self.header.timeout_ms if timeout_ms is None else timeout_ms,
            }
        )
        derived_address = self.address.model_copy(
            update={
                "source_node": self.address.source_node if source_node is None else source_node,
                "destination_node": self.address.destination_node if destination_node is None else destination_node,
                "reply_to": self.address.reply_to if reply_to is None else reply_to,
            }
        )
        derived_payload = dict(self.payload if payload is None else payload)
        derived_provenance = self.provenance if provenance is None else provenance
        derived_lineage = TransportLineage(
            parent_id=self.header.packet_id,
            root_id=self.lineage.root_id,
            generation=self.lineage.generation + 1,
        )

        payload_hash = _sha256_hex(derived_payload)
        transport_hash = _sha256_hex(
            self._transport_core_dict(
                header=derived_header,
                address=derived_address,
                payload=derived_payload,
                provenance=derived_provenance,
                lineage=derived_lineage,
                payload_hash=payload_hash,
            )
        )

        return TransportPacket(
            header=derived_header,
            address=derived_address,
            tenant=self.tenant,
            payload=derived_payload,
            security=self.security.model_copy(
                update={
                    "payload_hash": payload_hash,
                    "transport_hash": transport_hash,
                    "signature": None,
                    "signature_algorithm": None,
                    "signing_key_id": None,
                }
            ),
            governance=self.governance.model_copy(update={"intent": next_action}),
            provenance=derived_provenance,
            delegation_chain=self.delegation_chain,
            hop_trace=self.hop_trace,
            lineage=derived_lineage,
            attachments=self.attachments,
        )

    def with_hop(self, hop: TransportHop) -> "TransportPacket":
        return self.model_copy(update={"hop_trace": self.hop_trace + (hop,)})


def create_transport_packet(
    *,
    action: str,
    payload: Mapping[str, Any],
    tenant: str | Mapping[str, Any],
    destination_node: str,
    source_node: str,
    reply_to: str,
    packet_type: str = "request",
    idempotency_key: str | None = None,
    timeout_ms: int = 30_000,
    priority: int = 2,
    classification: str = "internal",
    encryption_status: str = "plaintext",
    compliance_tags: tuple[str, ...] = (),
    audit_required: bool = False,
    provenance: RoutingProvenance | None = None,
) -> TransportPacket:
    normalized_payload = dict(payload)
    tenant_context = TenantContext.from_value(tenant)

    header = TransportHeader(
        packet_type=packet_type,
        action=action,
        priority=priority,
        timeout_ms=timeout_ms,
        idempotency_key=idempotency_key,
    )
    address = TransportAddress(
        source_node=source_node,
        destination_node=destination_node,
        reply_to=reply_to,
    )

    if provenance is None:
        origin_kind = "client" if address.source_node == "client" else "node"
        provenance = RoutingProvenance(
            origin_kind=origin_kind,
            requested_action=header.action,
            resolved_by_gate=False,
            original_source_node=None if origin_kind == "client" else address.source_node,
        )

    payload_hash = _sha256_hex(normalized_payload)
    lineage = TransportLineage(
        parent_id=None,
        root_id=header.packet_id,
        generation=0,
    )
    governance = GovernanceEnvelope(
        intent=header.action,
        compliance_tags=compliance_tags,
        audit_required=audit_required,
    )

    transport_hash = _sha256_hex(
        {
            "header": header.model_dump(mode="json"),
            "address": address.model_dump(mode="json"),
            "tenant": tenant_context.model_dump(mode="json"),
            "payload": normalized_payload,
            "governance": governance.model_dump(mode="json"),
            "provenance": provenance.model_dump(mode="json"),
            "delegation_chain": [],
            "lineage": lineage.model_dump(mode="json"),
            "attachments": [],
            "payload_hash": payload_hash,
        }
    )

    return TransportPacket(
        header=header,
        address=address,
        tenant=tenant_context,
        payload=normalized_payload,
        security=SecurityEnvelope(
            payload_hash=payload_hash,
            transport_hash=transport_hash,
            classification=classification,
            encryption_status=encryption_status,
        ),
        governance=governance,
        provenance=provenance,
        lineage=lineage,
    )

# filename: src/constellation_node_sdk/runtime/node_runtime.py
from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from constellation_node_sdk.gate.client import GateClient
from constellation_node_sdk.transport.packet import RoutingProvenance, TransportPacket

Handler = Callable[..., Awaitable[dict[str, Any] | TransportPacket] | dict[str, Any] | TransportPacket]


class NodeRuntime:
    """
    Minimal production-aligned node runtime scaffold.

    Guarantees:
    - accepts canonical TransportPacket only
    - executes local handlers only
    - never routes directly to peer nodes
    - uses GateClient for follow-up work
    """

    def __init__(
        self,
        *,
        node_name: str,
        gate_url: str,
        service_name: str | None = None,
        version: str = "1.0.0",
    ) -> None:
        normalized_node_name = node_name.strip().lower()
        if not normalized_node_name:
            raise ValueError("node_name must not be blank")

        self.node_name = normalized_node_name
        self.service_name = service_name or normalized_node_name
        self.version = version
        self.gate_client = GateClient(gate_url, source_node=normalized_node_name)
        self._handlers: dict[str, Handler] = {}

    def handler(self, action: str) -> Callable[[Handler], Handler]:
        normalized_action = action.strip().lower()
        if not normalized_action:
            raise ValueError("action must not be blank")

        def decorator(func: Handler) -> Handler:
            self._handlers[normalized_action] = func
            return func

        return decorator

    def get_handler(self, action: str) -> Handler | None:
        return self._handlers.get(action.strip().lower())

    async def send_via_gate(
        self,
        *,
        parent: TransportPacket,
        action: str,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
        timeout_ms: int | None = None,
    ) -> TransportPacket:
        child = parent.derive(
            action=action,
            source_node=self.node_name,
            destination_node="gate",
            reply_to=self.node_name,
            payload=payload,
            idempotency_key=idempotency_key,
            timeout_ms=parent.header.timeout_ms if timeout_ms is None else timeout_ms,
            provenance=RoutingProvenance(
                origin_kind="node",
                requested_action=action,
                resolved_by_gate=False,
                original_source_node=self.node_name,
            ),
        )
        return await self.gate_client.send_to_gate(child)

    async def _invoke_handler(self, handler: Handler, packet: TransportPacket) -> dict[str, Any] | TransportPacket:
        parameters = list(inspect.signature(handler).parameters.values())

        if len(parameters) == 1:
            result = handler(packet)
        elif len(parameters) == 2:
            result = handler(packet.tenant.org_id, packet.payload)
        elif len(parameters) == 3:
            result = handler(packet.tenant.org_id, packet.payload, packet)
        else:
            raise TypeError("handler must accept (packet) or (tenant, payload) or (tenant, payload, packet)")

        if inspect.isawaitable(result):
            return await result
        return result

    def _response_packet_from_result(
        self,
        *,
        request_packet: TransportPacket,
        result: dict[str, Any] | TransportPacket,
    ) -> TransportPacket:
        if isinstance(result, TransportPacket):
            return result

        return request_packet.derive(
            packet_type="response",
            source_node=self.node_name,
            destination_node=request_packet.address.reply_to,
            reply_to=self.node_name,
            payload=result,
            provenance=RoutingProvenance(
                origin_kind="node",
                requested_action=request_packet.header.action,
                resolved_by_gate=False,
                original_source_node=self.node_name,
            ),
        )

    def _failure_packet(self, *, request_packet: TransportPacket, exc: Exception) -> TransportPacket:
        return request_packet.derive(
            packet_type="failure",
            source_node=self.node_name,
            destination_node=request_packet.address.reply_to,
            reply_to=self.node_name,
            payload={
                "status": "failed",
                "error": exc.__class__.__name__,
                "message": str(exc),
            },
            provenance=RoutingProvenance(
                origin_kind="node",
                requested_action=request_packet.header.action,
                resolved_by_gate=False,
                original_source_node=self.node_name,
            ),
        )

    def create_app(self) -> FastAPI:
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            app.state.runtime = self
            yield

        app = FastAPI(title=self.service_name, version=self.version, lifespan=lifespan)

        @app.get("/v1/health")
        async def health() -> dict[str, Any]:
            return {
                "status": "healthy",
                "service_name": self.service_name,
                "node_name": self.node_name,
                "version": self.version,
            }

        @app.post("/v1/execute")
        async def execute(request: Request) -> JSONResponse:
            packet: TransportPacket | None = None
            try:
                body = await request.json()
                if not isinstance(body, dict):
                    raise ValueError("request body must be a JSON object")

                packet = TransportPacket.model_validate(body)

                if packet.address.destination_node != self.node_name:
                    raise ValueError("packet destination does not match this node")

                handler = self.get_handler(packet.header.action)
                if handler is None:
                    raise LookupError(f"no handler registered for action: {packet.header.action}")

                result = await self._invoke_handler(handler, packet)
                response_packet = self._response_packet_from_result(
                    request_packet=packet,
                    result=result,
                )
                return JSONResponse(content=response_packet.model_dump_json_dict())

            except LookupError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except Exception as exc:  # noqa: BLE001
                if packet is not None:
                    failure_packet = self._failure_packet(request_packet=packet, exc=exc)
                    return JSONResponse(content=failure_packet.model_dump_json_dict(), status_code=200)
                raise HTTPException(status_code=500, detail="internal server error") from exc

