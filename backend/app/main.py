from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.adapters.app_api import API_PREFIX, build_router
from app.adapters.bot import build_runtime as build_bot_runtime
from app.adapters.bot import build_webhook_router
from app.adapters.bot import set_runtime as set_bot_runtime
from app.adapters.bot import shutdown as shutdown_bot
from app.adapters.bot import start as start_bot
from app.adapters.http.body_limit import BodyLimitMiddleware
from app.adapters.http.errors import install_error_handlers
from app.adapters.http.middleware import RequestContextMiddleware
from app.adapters.integration_api import API_PREFIX as INTEGRATION_PREFIX
from app.adapters.integration_api import build_app as build_integration_app
from app.adapters.operator import build_operator_router
from app.adapters.ops import build_ops_router
from app.db import session as db_session
from app.db.schema_revisions import SchemaError, check_schema
from app.infra.config import get_settings
from app.infra.crypto_keys import verify_on_startup as verify_secrets_key
from app.infra.logging import configure_logging

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await verify_secrets_key()
    await start_bot()
    yield
    await shutdown_bot()
    await db_session.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.app_env)
    is_prod = settings.app_env == "prod"

    app = FastAPI(
        title="Сервис ремонта оборудования — пользовательский API",
        version="1.0.0",
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=None if is_prod else "/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    async def readyz() -> JSONResponse:
        try:
            await _check_database()
        except SchemaError as exc:
            log.warning("readyz_failed", reason=type(exc).__name__, detail=str(exc))
            return JSONResponse({"status": "unavailable"}, status_code=503)
        except Exception as exc:
            log.warning("readyz_failed", reason=type(exc).__name__)
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return JSONResponse({"status": "ok"})

    app.include_router(build_router())
    app.include_router(build_operator_router())
    app.include_router(build_ops_router())
    bot_runtime = build_bot_runtime(settings)
    set_bot_runtime(bot_runtime)
    if bot_runtime is not None and bot_runtime.mode == "webhook":
        app.include_router(build_webhook_router())
    app.mount(INTEGRATION_PREFIX, build_integration_app())
    return app


async def _check_database() -> None:
    await check_schema(db_session.get_engine())


app = create_app()
