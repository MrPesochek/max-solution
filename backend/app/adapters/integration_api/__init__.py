from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.dependencies.models import Dependant
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from app.adapters.http.errors import error_response, install_error_handlers
from app.adapters.integration_api.deps import RequireScope
from app.adapters.integration_api.rate_limit import RateLimitExceeded, headers_of
from app.adapters.integration_api.routers import (
    attachments,
    equipment,
    events,
    marketplace,
    me,
    requests,
    reviews,
    service_bindings,
    webhook_subscriptions,
)
from app.infra.config import get_settings

API_PREFIX = "/api/v1"
SCOPES_EXTENSION = "x-required-scopes"

ROUTERS: tuple[APIRouter, ...] = (
    me.router,
    webhook_subscriptions.router,
    events.router,
    requests.router,
    marketplace.router,
    attachments.router,
    reviews.router,
    equipment.router,
    service_bindings.bindings_router,
    service_bindings.invitations_router,
)


def api_routes() -> list[APIRoute]:
    return [route for router in ROUTERS for route in router.routes if isinstance(route, APIRoute)]


def route_scopes(route: APIRoute) -> list[RequireScope]:
    """Все объявления scope в дереве зависимостей маршрута."""
    found: list[RequireScope] = []

    def walk(dependant: Dependant) -> None:
        if isinstance(dependant.call, RequireScope):
            found.append(dependant.call)
        for child in dependant.dependencies:
            walk(child)

    walk(route.dependant)
    return found


def _scope_note(scopes: tuple[str, ...]) -> str:
    if not scopes:
        return "Не требует дополнительного scope — доступен с любым действующим ключом."
    listed = " или ".join(f"`{s}`" for s in scopes)
    return f"Требует scope {listed}."


def _build_openapi(app: FastAPI) -> dict[str, Any]:
    if app.openapi_schema is not None:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version=app.openapi_version,
        routes=app.routes,
        servers=app.servers,
    )
    for route in api_routes():
        declared = route_scopes(route)
        if not declared:
            continue
        scopes = declared[0].scopes
        for method in route.methods or ():
            operation = schema["paths"].get(route.path_format, {}).get(method.lower())
            if operation is None:
                continue
            operation[SCOPES_EXTENSION] = list(scopes)
            note = _scope_note(scopes)
            description = operation.get("description")
            operation["description"] = f"{description}\n\n{note}" if description else note
    app.openapi_schema = schema
    return schema


def build_app() -> FastAPI:
    is_prod = get_settings().app_env == "prod"
    app = FastAPI(
        title="Сервис ремонта оборудования — интеграционный API",
        version="1.0.0",
        openapi_url="/openapi.json",
        docs_url=None if is_prod else "/docs",
        redoc_url=None,
        servers=[{"url": API_PREFIX, "description": "Интеграционный API, версия 1"}],
    )
    install_error_handlers(app)

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limited(request: Request, exc: RateLimitExceeded) -> JSONResponse:
        response = error_response(request, exc.status, exc.code, exc.message, exc.details)
        response.headers.update(headers_of(exc.decision))
        response.headers["Retry-After"] = str(exc.decision.reset_after)
        return response

    for router in ROUTERS:
        app.include_router(router)
    app.openapi = lambda: _build_openapi(app)  # type: ignore[method-assign]
    return app
