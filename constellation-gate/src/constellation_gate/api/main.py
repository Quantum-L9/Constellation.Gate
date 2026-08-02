from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, Query, Request, Response
from fastapi.responses import JSONResponse

from constellation_gate.api import dependencies as deps
from constellation_gate.api.errors import to_http_exception
from constellation_gate.runtime.app_state import AppState
from constellation_gate.runtime.metrics_endpoint import router as metrics_router
from constellation_gate.schemas.registry import RegisterNodesRequest
from constellation_gate.services.capability_service import CapabilityAuthorizationError


def create_app() -> FastAPI:
    http_client_manager = deps.get_http_client_manager()
    node_limiter_manager = deps.get_node_limiter_manager()
    state = AppState()
    state.attach_runtime(
        http_client_manager=http_client_manager,
        node_limiter_manager=node_limiter_manager,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.runtime = state
        await http_client_manager.startup()
        try:
            yield
        finally:
            await http_client_manager.shutdown()

    app = FastAPI(title="constellation-gate", version="1.0.0", lifespan=lifespan)
    app.include_router(metrics_router)

    @app.get("/v1/health")
    async def health() -> dict[str, Any]:
        settings = deps.get_gate_settings()
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
            service = deps.get_execute_service()
            packet = await service.execute(body)
            return JSONResponse(content=packet.model_dump_json_dict())
        except Exception as exc:  # noqa: BLE001
            raise to_http_exception(exc) from exc

    @app.get("/v1/registry")
    async def registry_snapshot() -> dict[str, dict[str, Any]]:
        try:
            service = deps.get_registry_query_service()
            return service.snapshot()
        except Exception as exc:  # noqa: BLE001
            raise to_http_exception(exc) from exc

    @app.get("/v1/capabilities")
    async def list_capabilities(
        response: Response,
        include_protected: bool = Query(False),
        if_none_match: str | None = Header(default=None, alias="If-None-Match"),
        x_admin_token: str | None = Header(default=None),
    ) -> Any:
        try:
            service = deps.get_capability_service()
            payload = service.list_capabilities(
                presented_token=x_admin_token,
                include_protected=include_protected,
            )
            if if_none_match is not None and if_none_match.strip() == payload.etag:
                return Response(status_code=304, headers={"ETag": payload.etag})
            response.headers["ETag"] = payload.etag
            return payload.model_dump(mode="json")
        except CapabilityAuthorizationError as exc:
            raise to_http_exception(exc) from exc
        except Exception as exc:  # noqa: BLE001
            raise to_http_exception(exc) from exc

    @app.get("/v1/capabilities/{action}")
    async def get_capability(
        action: str,
        response: Response,
        if_none_match: str | None = Header(default=None, alias="If-None-Match"),
        x_admin_token: str | None = Header(default=None),
    ) -> Any:
        try:
            service = deps.get_capability_service()
            descriptor, etag = service.get_capability(action, presented_token=x_admin_token)
            if if_none_match is not None and if_none_match.strip() == etag:
                return Response(status_code=304, headers={"ETag": etag})
            response.headers["ETag"] = etag
            return descriptor.model_dump(mode="json")
        except CapabilityAuthorizationError as exc:
            raise to_http_exception(exc) from exc
        except Exception as exc:  # noqa: BLE001
            raise to_http_exception(exc) from exc

    @app.post("/v1/admin/register")
    async def admin_register(
        request: RegisterNodesRequest,
        overwrite: bool = Query(True),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        try:
            service = deps.get_admin_registration_service()
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
