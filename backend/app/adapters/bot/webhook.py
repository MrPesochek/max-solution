from __future__ import annotations

import structlog
from fastapi import APIRouter, Request, Response
from maxapi.methods.types.getted_updates import process_update_webhook

from app.adapters.bot import updates
from app.adapters.bot.runtime import WEBHOOK_PATH, get_runtime
from app.adapters.bot.webhook_secret import secret_ok

log = structlog.get_logger("bot")

SECRET_HEADER = "X-Max-Bot-Api-Secret"


def build_webhook_router() -> APIRouter:
    router = APIRouter()

    @router.post(WEBHOOK_PATH, include_in_schema=False)
    async def receive(request: Request) -> Response:
        runtime = get_runtime()
        if runtime is None:
            return Response(status_code=404)
        if not await secret_ok(runtime, request.headers.get(SECRET_HEADER)):
            log.warning("max_webhook_bad_secret")
            return Response(status_code=403)

        try:
            payload = await request.json()
        except Exception:
            return Response(status_code=400)
        if not isinstance(payload, dict):
            return Response(status_code=400)

        event = await process_update_webhook(event_json=payload, bot=runtime.bot)
        if event is None:
            log.warning("max_webhook_unknown_update", update_type=str(payload.get("update_type")))
            return Response(status_code=200)

        try:
            await updates.process(runtime.dispatcher, event)
        except Exception:
            log.exception("max_webhook_record_failed")
            return Response(status_code=503)
        return Response(status_code=200)

    return router
