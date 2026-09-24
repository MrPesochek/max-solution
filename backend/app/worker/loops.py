from datetime import datetime

import structlog

from app.adapters.bot import ensure_subscription
from app.infra.config import Settings
from app.modules.trust import api as trust
from app.worker import (
    cleanup,
    feed_dispatcher,
    image_processor,
    max_updates_recovery,
    notification_dispatcher,
    ops_monitor,
    request_sweeper,
    webhook_dispatcher,
)
from app.worker.runner import Loop

log = structlog.get_logger(__name__)


async def _check_bot_subscription(now: datetime) -> int:
    del now
    return 1 if await ensure_subscription() else 0


def build_loops(settings: Settings) -> list[Loop]:
    loops = [
        Loop("feed_dispatcher", feed_dispatcher.run_once, settings.feed_dispatch_interval_seconds),
        Loop(
            "webhook_dispatcher",
            webhook_dispatcher.run_once,
            settings.webhook_dispatch_interval_seconds,
        ),
        Loop(
            "notification_dispatcher",
            notification_dispatcher.run_once,
            settings.notification_dispatch_interval_seconds,
        ),
        Loop("cleanup", cleanup.run_once, settings.cleanup_interval_seconds),
        Loop("request_sweeper", request_sweeper.run_once, settings.sweeper_interval_seconds),
        Loop(
            "image_processor",
            image_processor.run_once,
            settings.image_processing_interval_seconds,
        ),
        Loop("file_cleanup", image_processor.run_cleanup, settings.cleanup_interval_seconds),
        Loop(
            "verification_expiry",
            trust.expire_verifications,
            settings.verification_expiry_interval_seconds,
        ),
        Loop("ops_monitor", ops_monitor.run_once, settings.ops_monitor_interval_seconds),
        Loop(
            "max_updates_recovery",
            max_updates_recovery.run_once,
            settings.max_update_recovery_interval_seconds,
        ),
    ]
    if settings.max_updates_mode == "webhook":
        loops.append(
            Loop(
                "bot_subscription",
                _check_bot_subscription,
                settings.bot_subscription_check_interval_seconds,
            )
        )
    return loops
