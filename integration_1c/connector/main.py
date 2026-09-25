from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from connector import db as db_module
from connector import repo
from connector.onec_client import OneCClient
from connector.platform_client import PlatformClient
from connector.profile import load_profile
from connector.services import outbound
from connector.services.bootstrap import bootstrap_retry_loop
from connector.services.recovery import recovery_loop
from connector.settings import Settings, get_settings
from connector.state import AppState
from connector.webhooks import router as webhooks_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("onec_connector")


def build_state(settings: Settings) -> AppState:
    profile = load_profile(settings.profile_path())
    if settings.verify_tls() is False:
        logger.warning("проверка TLS-сертификата 1С отключена (CONNECTOR_ONEC_VERIFY_TLS=false)")
    return AppState(
        conn=db_module.connect(settings.database_file()),
        client=PlatformClient(settings),
        onec=OneCClient(settings),
        profile=profile,
        settings=settings,
    )


async def poll_loop(state: AppState) -> None:
    while True:
        try:
            await outbound.poll_once(state)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("опрос 1С не удался", exc_info=True)
        await asyncio.sleep(state.settings.poll_interval_seconds)


def create_app(state: AppState | None = None, *, run_loops: bool = True) -> FastAPI:
    """`state`/`run_loops=False` — для тестов: подменённые платформа и 1С, без фоновых циклов."""
    owns_state = state is None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        nonlocal state
        if state is None:
            state = build_state(get_settings())
        app.state.connector = state
        loops: list[asyncio.Task[None]] = []
        if run_loops:
            coroutines: list[Coroutine[Any, Any, None]] = [
                bootstrap_retry_loop(state),
                recovery_loop(state),
                poll_loop(state),
            ]
            loops = [asyncio.create_task(c) for c in coroutines]
        try:
            yield
        finally:
            for task in [*loops, *state.background_tasks]:
                task.cancel()
            pending = [*loops, *state.background_tasks]
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            if owns_state:
                await state.client.aclose()
                await state.onec.aclose()
                state.conn.close()

    app = FastAPI(title="Коннектор 1С", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.include_router(webhooks_router)

    @app.get("/healthz")
    async def healthz() -> PlainTextResponse:
        return PlainTextResponse("ok")

    @app.get("/status")
    async def status(request: Request) -> JSONResponse:
        current: AppState = request.app.state.connector
        subscription = repo.get_subscription(current.conn)
        return JSONResponse(
            {
                "profile": current.profile.name,
                "subscription": bool(subscription and subscription["subscription_id"]),
                "active_links": len(repo.list_active_links(current.conn)),
                "events_cursor": repo.get_cursor(current.conn),
                "failed_events": repo.count_events(current.conn, "failed"),
                "dead_events": repo.count_events(current.conn, "dead"),
            }
        )

    return app


app = create_app()
