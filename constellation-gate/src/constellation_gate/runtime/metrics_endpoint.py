from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import generate_latest

from constellation_gate.observability.metrics import REGISTRY

router = APIRouter()


@router.get("/metrics")
def metrics() -> Response:
    data = generate_latest(REGISTRY)
    return Response(content=data, media_type="text/plain; version=0.0.4")
