"""The transport seam classifies failures instead of flattening them.

Collapsing every failure into RuntimeError loses the distinction the caller
needs: "the worker is down" (mark it unhealthy), "it did not answer in time"
(say nothing about its health), "it answered with something unusable" (an
upstream bug). Dispatcher acts differently on each.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from constellation_node_sdk.transport.packet import create_transport_packet

from constellation_gate.routing.worker_transport import (
    WorkerResponseError,
    WorkerTimeoutError,
    WorkerTransportError,
    WorkerUnreachableError,
    post_worker_packet,
)


class ScriptedClient:
    def __init__(self, outcome: Any) -> None:
        self._outcome = outcome
        self.timeouts: list[float] = []

    async def post(self, url: str, json: dict, headers: dict, timeout: float):
        self.timeouts.append(timeout)
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


def _packet():
    return create_transport_packet(
        action="score",
        payload={"a": 1},
        tenant="tenant-a",
        destination_node="worker",
        source_node="gate",
        reply_to="gate",
    )


async def _post(client: Any, *, timeout_seconds: float = 5.0):
    return await post_worker_packet(
        packet=_packet(),
        url="http://worker:8000/v1/execute",
        timeout_seconds=timeout_seconds,
        node_name="worker",
        client=client,
    )


def _response(*, status_code: int = 200, json_body: Any = None, text: str | None = None):
    request = httpx.Request("POST", "http://worker:8000/v1/execute")
    if text is not None:
        return httpx.Response(status_code=status_code, text=text, request=request)
    return httpx.Response(status_code=status_code, json=json_body, request=request)


@pytest.mark.asyncio
async def test_successful_post_returns_the_decoded_body() -> None:
    body = _packet().model_dump_json_dict()
    result = await _post(ScriptedClient(_response(json_body=body)))
    assert result["header"]["action"] == "score"


@pytest.mark.asyncio
async def test_connect_failure_is_unreachable_not_timeout() -> None:
    exc = await _raises(httpx.ConnectError("refused"))
    assert isinstance(exc, WorkerUnreachableError)
    assert not isinstance(exc, TimeoutError)
    assert exc.node_name == "worker"


@pytest.mark.asyncio
async def test_timeout_is_a_timeout_error_and_not_unreachable() -> None:
    """Health matters here: a slow worker must not be ejected from routing."""
    exc = await _raises(httpx.ReadTimeout("slow"))
    assert isinstance(exc, WorkerTimeoutError)
    assert isinstance(exc, TimeoutError)
    assert not isinstance(exc, WorkerUnreachableError)


@pytest.mark.asyncio
async def test_http_error_status_is_a_response_error_carrying_the_code() -> None:
    with pytest.raises(WorkerResponseError) as info:
        await _post(ScriptedClient(_response(status_code=503, json_body={})))
    assert info.value.status_code == 503
    assert not isinstance(info.value, TimeoutError)


@pytest.mark.asyncio
async def test_non_json_body_is_a_response_error() -> None:
    with pytest.raises(WorkerResponseError):
        await _post(ScriptedClient(_response(text="not json at all")))


@pytest.mark.asyncio
async def test_non_object_json_body_is_a_response_error() -> None:
    with pytest.raises(WorkerResponseError):
        await _post(ScriptedClient(_response(json_body=[1, 2, 3])))


@pytest.mark.asyncio
async def test_exhausted_budget_never_touches_the_network() -> None:
    client = ScriptedClient(_response(json_body={}))
    with pytest.raises(WorkerTimeoutError):
        await _post(client, timeout_seconds=0)
    assert client.timeouts == []


@pytest.mark.asyncio
async def test_the_budget_reaches_the_real_client() -> None:
    client = ScriptedClient(_response(json_body=_packet().model_dump_json_dict()))
    await _post(client, timeout_seconds=2.5)
    assert client.timeouts == [2.5]


@pytest.mark.asyncio
async def test_every_failure_is_a_worker_transport_error() -> None:
    """One base class, so a caller can catch the category without listing members."""
    for outcome in (httpx.ConnectError("x"), httpx.ReadTimeout("x")):
        exc = await _raises(outcome)
        assert isinstance(exc, WorkerTransportError)


async def _raises(outcome: Exception) -> Exception:
    with pytest.raises(WorkerTransportError) as info:
        await _post(ScriptedClient(outcome))
    return info.value
