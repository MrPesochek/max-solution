from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from emulator import store
from emulator.odata import router as odata_router
from emulator.settings import Settings, get_settings
from emulator.state import EmulatorState
from emulator.web.auth import NotAuthenticated, is_authenticated
from emulator.web.auth import router as auth_router
from emulator.web.routes_ui import router as ui_router

logging.basicConfig(level=logging.INFO)


def build_state(settings: Settings, *, in_memory: bool = False) -> EmulatorState:
    conn = store.connect(None if in_memory else settings.database_file())
    store.seed(conn)
    return EmulatorState(conn=conn, settings=settings)


def create_app(state: EmulatorState | None = None) -> FastAPI:
    owns_state = state is None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        nonlocal state
        if state is None:
            state = build_state(get_settings())
        app.state.emulator = state
        try:
            yield
        finally:
            if owns_state:
                state.conn.close()

    app = FastAPI(title="Эмулятор 1С", lifespan=lifespan, docs_url=None, redoc_url=None)
    static_dir = Path(__file__).parent / "web" / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    app.include_router(auth_router)
    app.include_router(ui_router)
    app.include_router(odata_router)

    @app.exception_handler(NotAuthenticated)
    async def _not_authenticated(request: Request, exc: NotAuthenticated) -> RedirectResponse:
        return RedirectResponse("/login", status_code=303)

    @app.get("/healthz")
    async def healthz() -> PlainTextResponse:
        return PlainTextResponse("ok")

    @app.get("/")
    async def root(request: Request) -> RedirectResponse:
        target = "/ui/orders" if is_authenticated(request) else "/login"
        return RedirectResponse(target, status_code=303)

    return app


app = create_app()
