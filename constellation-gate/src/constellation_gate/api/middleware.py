from __future__ import annotations

import time
from uuid import uuid4

from fastapi import Request
from starlette.responses import Response


async def request_context_middleware(request: Request, call_next) -> Response:
    request_id = request.headers.get("x-request-id", str(uuid4()))
    request.state.request_id = request_id
    started_at = time.perf_counter()

    response = await call_next(request)

    duration_ms = int((time.perf_counter() - started_at) * 1000)
    response.headers["x-request-id"] = request_id
    response.headers["x-execution-ms"] = str(duration_ms)
    return response
