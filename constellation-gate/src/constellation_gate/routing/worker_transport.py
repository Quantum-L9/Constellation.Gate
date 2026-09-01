"""The single Gate->worker packet-transport adapter.

ARCHITECTURAL SEAM -- read before adding an HTTP call anywhere else.

Gate decides *where*. Transport mechanics (serialization, the POST, network
timeout, status mapping, response decoding, response packet validation) decide
*how*. This module is the only place in Gate production code allowed to own the
"how" for a worker packet, and ``tests/architecture/test_worker_transport_seam.py``
fails the build if a second one appears.

It exists as Gate-local code only because the SDK does not yet expose a
Gate-authorized worker-transport primitive: ``GateClient`` is structurally
node->Gate (it asserts ``origin_kind == "node"`` and a Gate-only destination),
so a Gate-authored dispatch packet cannot pass through it. See
GATE_SDK_REQUIRED_DELTA.md for the exact missing API. When the SDK ships it,
the body of ``post_worker_packet`` is replaced by that call and the seam test
keeps holding the boundary.
"""

from __future__ import annotations

from typing import Any

import httpx
from constellation_node_sdk.transport.packet import TransportPacket


class WorkerTransportError(RuntimeError):
    """Base class for Gate->worker transport failures.

    Carries the target node so a caller can attribute the failure without
    re-parsing an httpx exception.
    """

    def __init__(self, message: str, *, node_name: str) -> None:
        super().__init__(message)
        self.node_name = node_name


class WorkerUnreachableError(WorkerTransportError):
    """The worker could not be reached (connect/DNS/TLS/socket failure)."""


class WorkerTimeoutError(WorkerTransportError, TimeoutError):
    """The worker did not answer inside the budget granted to this call.

    Also a ``TimeoutError`` so timeout-shaped handling keeps working. Note that
    this means "no answer arrived", never "no work happened" -- which is exactly
    why it does not authorize a whole-operation replay on its own.
    """


class WorkerResponseError(WorkerTransportError):
    """The worker answered, but not with a usable canonical response."""

    def __init__(self, message: str, *, node_name: str, status_code: int | None = None) -> None:
        super().__init__(message, node_name=node_name)
        self.status_code = status_code


async def post_worker_packet(
    *,
    packet: TransportPacket,
    url: str,
    timeout_seconds: float,
    node_name: str,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """POST a Gate-authored packet to a worker's ``/v1/execute``.

    ``timeout_seconds`` is the budget this call may consume and is applied to
    the real network client, not merely to an awaiting wrapper.
    """
    if timeout_seconds <= 0:
        raise WorkerTimeoutError(
            f"no remaining budget for dispatch to {node_name!r}",
            node_name=node_name,
        )

    body_json = packet.model_dump_json_dict()
    headers = {"Content-Type": "application/json"}

    try:
        if client is not None:
            response = await client.post(
                url, json=body_json, headers=headers, timeout=timeout_seconds
            )
        else:
            async with httpx.AsyncClient(timeout=timeout_seconds) as owned_client:
                response = await owned_client.post(url, json=body_json, headers=headers)
    except httpx.TimeoutException as exc:
        raise WorkerTimeoutError(
            f"dispatch to {node_name!r} timed out after {timeout_seconds:.3f}s",
            node_name=node_name,
        ) from exc
    except httpx.TransportError as exc:
        raise WorkerUnreachableError(
            f"dispatch transport error to {node_name!r}",
            node_name=node_name,
        ) from exc

    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise WorkerResponseError(
            f"worker {node_name!r} returned HTTP {response.status_code}",
            node_name=node_name,
            status_code=response.status_code,
        ) from exc

    try:
        body = response.json()
    except ValueError as exc:
        raise WorkerResponseError(
            f"worker {node_name!r} returned a non-JSON body",
            node_name=node_name,
            status_code=response.status_code,
        ) from exc

    if not isinstance(body, dict):
        raise WorkerResponseError(
            f"worker {node_name!r} response body must be a JSON object",
            node_name=node_name,
            status_code=response.status_code,
        )
    return body
