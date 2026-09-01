"""A worker backed by the real Gate_SDK runtime, reachable over ``httpx``.

Gate's dispatch tests used to answer with a hand-built response body. That could
not prove interoperability: a fake answers whatever the test wants, including
things no SDK worker would ever send, so a Gate change that broke a real worker
still passed.

This harness removes that gap. Requests are served by the SDK's own
``execute_transport_packet`` -- the same ingress validation, replay policy,
handler dispatch, and response derivation a deployed worker runs -- mounted
behind a real ``httpx.AsyncBaseTransport`` so it is exercised through an actual
``httpx.AsyncClient`` without needing a socket. A packet Gate sends here must
satisfy the checks a production worker applies, and the answer that comes back is
one a production worker would actually have produced.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx
from constellation_node_sdk.runtime.execution import execute_transport_packet
from constellation_node_sdk.runtime.handlers import clear_handlers, register_handler
from constellation_node_sdk.runtime.inbound_policy import validate_execute_ingress_packet
from constellation_node_sdk.transport.packet import TransportPacket


class SdkWorker:
    """An SDK-backed worker node addressable at ``http://<node>:8000``."""

    def __init__(
        self,
        *,
        node_name: str = "worker",
        action: str = "score",
        handler: Callable[..., Any] | None = None,
        require_signature: bool = False,
        signing_key: str | bytes | None = None,
        signing_key_id: str | None = None,
        signing_algorithm: str | None = None,
        verifying_keys: dict[str, str] | None = None,
        blocking: bool = False,
        gate_node_name: str | None = None,
    ) -> None:
        self.node_name = node_name
        self.action = action
        self.requests: list[httpx.Request] = []
        self.received_packets: list[TransportPacket] = []
        # The budget the worker runtime was told to bound this call with. Read
        # by the deadline tests: it is the number the worker actually sees, not
        # one the test asserts about second-hand.
        self.observed_timeout_ms: list[int] = []
        # The deadline httpx actually applied to the socket, as the SDK derived
        # it. Recorded alongside the header budget so a test can assert the two
        # are the same number rather than trusting that they are.
        self.observed_socket_timeout: list[float] = []
        self._require_signature = require_signature
        self._signing_key = signing_key
        self._signing_key_id = signing_key_id
        self._signing_algorithm = signing_algorithm
        self._verifying_keys = verifying_keys or {}
        # When set, the worker applies the SDK's own /v1/execute ingress policy
        # explicitly and records anything it rejects. That is the cross-repo
        # contract in one line: a packet Gate derived must satisfy the same rule
        # a deployed worker applies, not a fixture written to agree with Gate.
        self._gate_node_name = gate_node_name
        self.ingress_errors: list[Exception] = []

        # Concurrency tests need a worker that is genuinely mid-call: ``entered``
        # fires once a request is being served, and the call does not complete
        # until ``release`` is set. Opt-in so ordinary tests stay synchronous.
        self._blocking = blocking
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

        clear_handlers()
        register_handler(action, handler or self._echo_handler)

    @staticmethod
    def _echo_handler(org_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Return the payload untouched, so opacity is observable end to end.

        Two parameters deliberately: the SDK dispatches a handler by arity, and
        ``(org_id, payload)`` is the shape a real worker's business handler uses.
        """
        return payload

    async def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self.observed_socket_timeout.append(request.extensions["timeout"]["read"])

        body = json.loads(request.content.decode("utf-8"))
        inbound = TransportPacket.model_validate(body)
        self.received_packets.append(inbound)
        self.observed_timeout_ms.append(inbound.header.timeout_ms)

        if self._gate_node_name is not None:
            try:
                validate_execute_ingress_packet(
                    inbound,
                    local_node=self.node_name,
                    gate_node_name=self._gate_node_name,
                    require_route_kind=True,
                )
            except Exception as exc:  # surfaced by the test, never swallowed
                self.ingress_errors.append(exc)
                raise

        if self._blocking:
            self.entered.set()
            await self.release.wait()

        response_packet = await execute_transport_packet(
            inbound,
            node_name=self.node_name,
            require_signature=self._require_signature,
            dev_mode=not self._require_signature,
            signing_key=self._signing_key,
            signing_key_id=self._signing_key_id,
            signing_algorithm=self._signing_algorithm,
            verifying_keys=self._verifying_keys or None,
        )
        return httpx.Response(
            status_code=200,
            json=response_packet.model_dump_json_dict(),
            request=request,
        )

    def transport(self) -> httpx.AsyncBaseTransport:
        """An httpx transport whose requests are served by the SDK runtime."""
        return _SdkWorkerTransport(self._handle)

    def client(self) -> httpx.AsyncClient:
        """A real ``httpx.AsyncClient`` whose requests reach this worker."""
        return httpx.AsyncClient(transport=self.transport())

    @property
    def request_count(self) -> int:
        return len(self.requests)


class _SdkWorkerTransport(httpx.AsyncBaseTransport):
    """Route httpx requests into an async handler.

    ``httpx.MockTransport`` invokes its handler synchronously, which cannot
    await the SDK's ``execute_transport_packet``. Answering that with a
    synchronous re-implementation of the worker would defeat the point of this
    harness, so the transport is async instead and the real runtime is awaited.
    """

    def __init__(self, handler: Callable[[httpx.Request], Any]) -> None:
        self._handler = handler

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self._handler(request)
