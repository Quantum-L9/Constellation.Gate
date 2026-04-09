from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse

from constellation_gate.api.dependencies import (
    get_admin_registration_service,
    get_execute_service,
    get_gate_settings,
    get_registry_query_service,
)
from constellation_gate.api.errors import to_http_exception
from constellation_gate.schemas.registry import RegisterNodesRequest


def create_app() -> FastAPI:
    app = FastAPI(title="constellation-gate", version="1.0.0")

    @app.get("/v1/health")
    async def health() -> dict[str, Any]:
        settings = get_gate_settings()
        return {
            "status": "healthy",
            "service_name": "constellation-gate",
            "node_name": settings.local_node,
            "environment": settings.environment,
        }

    @app.post("/v1/execute")
    async def execute(request: Request) -> JSONResponse:
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("request body must be a JSON object")
            service = get_execute_service()
            packet = await service.execute(body)
            return JSONResponse(content=packet.model_dump_json_dict())
        except Exception as exc:  # noqa: BLE001
            raise to_http_exception(exc) from exc

    @app.get("/v1/registry")
    async def registry_snapshot() -> dict[str, dict]:
        try:
            service = get_registry_query_service()
            return service.snapshot()
        except Exception as exc:  # noqa: BLE001
            raise to_http_exception(exc) from exc

    @app.post("/v1/admin/register")
    async def admin_register(
        request: RegisterNodesRequest,
        overwrite: bool = Query(True),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        try:
            service = get_admin_registration_service()
            response = await service.register(
                request=request,
                overwrite=overwrite,
                presented_token=x_admin_token,
            )
            return response.model_dump(mode="json")
        except Exception as exc:  # noqa: BLE001
            raise to_http_exception(exc) from exc

    return app


app = create_app()
