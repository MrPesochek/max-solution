from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.db import session as db_session
from app.db.enums import DeliveryState, NotificationState
from app.db.models import MaxUpdate, Notification, WebhookDelivery
from app.infra.config import Settings
from app.modules.ops.heartbeats import LoopHeartbeat, load_heartbeats

BOT_SUBSCRIPTION_LOOP = "bot_subscription"

_WEBHOOK_TERMINAL = (DeliveryState.FAILED.value, DeliveryState.BLOCKED.value, "dead")
_WEBHOOK_PENDING = (DeliveryState.QUEUED.value, DeliveryState.RETRYING.value)
_MAX_UPDATE_DEAD = ("dead",)
_MAX_UPDATE_PENDING = ("received", "processing", "failed")


@dataclass(frozen=True, slots=True)
class Alarm:
    """Причина degraded; `code` — машиночитаемый, по нему алертит лог-агент."""

    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class NotificationStats:
    by_state: dict[str, int]
    failed_recent: int
    oldest_queued_at: datetime | None
    oldest_queued_age_seconds: float | None


@dataclass(frozen=True, slots=True)
class WebhookStats:
    by_state: dict[str, int]
    failed_recent: int
    oldest_pending_at: datetime | None
    oldest_pending_age_seconds: float | None
    max_overdue_seconds: float | None


@dataclass(frozen=True, slots=True)
class MaxUpdateStats:
    by_state: dict[str, int]
    dead_recent: int
    oldest_pending_age_seconds: float | None
    last_received_at: datetime | None
    source: str


@dataclass(frozen=True, slots=True)
class SubscriptionStats:
    mode: str
    checked: bool
    last_checked_at: datetime | None
    last_error_at: datetime | None
    last_error: str | None
    failing: bool


@dataclass(frozen=True, slots=True)
class OpsStatus:
    checked_at: datetime
    heartbeats: list[LoopHeartbeat]
    notifications: NotificationStats
    webhooks: WebhookStats
    max_updates: MaxUpdateStats
    max_subscription: SubscriptionStats
    alarms: list[Alarm]

    @property
    def degraded(self) -> bool:
        return bool(self.alarms)

    def to_json(self) -> dict[str, Any]:
        return {
            "checked_at": _iso(self.checked_at),
            "degraded": self.degraded,
            "reasons": [
                {"code": alarm.code, "message": alarm.message, **alarm.details}
                for alarm in self.alarms
            ],
            "heartbeats": [
                {
                    "loop": beat.name,
                    "stale": beat.stale,
                    "failing": beat.failing,
                    "age_seconds": _round(beat.age_seconds),
                    "stale_after_seconds": beat.stale_after_seconds,
                    "last_success_at": _iso(beat.last_success_at),
                    "last_processed": beat.last_processed,
                    "last_error_at": _iso(beat.last_error_at),
                    "last_error": beat.last_error,
                    "consecutive_failures": beat.consecutive_failures,
                    "registered_at": _iso(beat.registered_at),
                }
                for beat in self.heartbeats
            ],
            "notifications": {
                "by_state": self.notifications.by_state,
                "pending": self.notifications.by_state.get(NotificationState.QUEUED.value, 0),
                "failed": self.notifications.by_state.get(NotificationState.FAILED.value, 0),
                "failed_recent": self.notifications.failed_recent,
                "oldest_pending_at": _iso(self.notifications.oldest_queued_at),
                "oldest_pending_age_seconds": _round(self.notifications.oldest_queued_age_seconds),
            },
            "webhooks": {
                "by_state": self.webhooks.by_state,
                "retrying": self.webhooks.by_state.get(DeliveryState.RETRYING.value, 0),
                "failed": self.webhooks.by_state.get(DeliveryState.FAILED.value, 0),
                "blocked": self.webhooks.by_state.get(DeliveryState.BLOCKED.value, 0),
                "dead": self.webhooks.by_state.get("dead", 0),
                "failed_recent": self.webhooks.failed_recent,
                "oldest_pending_at": _iso(self.webhooks.oldest_pending_at),
                "oldest_pending_age_seconds": _round(self.webhooks.oldest_pending_age_seconds),
                "max_overdue_seconds": _round(self.webhooks.max_overdue_seconds),
            },
            "max_updates": {
                "by_state": self.max_updates.by_state,
                "failed": self.max_updates.by_state.get("failed", 0),
                "dead": self.max_updates.by_state.get("dead", 0),
                "dead_recent": self.max_updates.dead_recent,
                "oldest_pending_age_seconds": _round(self.max_updates.oldest_pending_age_seconds),
                "last_received_at": _iso(self.max_updates.last_received_at),
                "source": self.max_updates.source,
            },
            "max_subscription": {
                "mode": self.max_subscription.mode,
                "checked": self.max_subscription.checked,
                "last_checked_at": _iso(self.max_subscription.last_checked_at),
                "last_error_at": _iso(self.max_subscription.last_error_at),
                "last_error": self.max_subscription.last_error,
                "failing": self.max_subscription.failing,
            },
        }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _round(value: float | None) -> float | None:
    return round(value, 1) if value is not None else None


def _age(now: datetime, moment: datetime | None) -> float | None:
    return max(0.0, (now - moment).total_seconds()) if moment is not None else None


async def _count_by(session: AsyncSession, column: Any) -> dict[str, int]:
    rows = await session.execute(select(column, func.count()).group_by(column))
    return {str(state): int(count) for state, count in rows.all()}


async def _notifications(
    session: AsyncSession, now: datetime, since: datetime
) -> NotificationStats:
    by_state = await _count_by(session, Notification.state)
    failed_recent = await session.scalar(
        select(func.count()).where(
            Notification.state == NotificationState.FAILED.value, Notification.created_at >= since
        )
    )
    oldest = await session.scalar(
        select(func.min(Notification.created_at)).where(
            Notification.state == NotificationState.QUEUED.value
        )
    )
    return NotificationStats(
        by_state=by_state,
        failed_recent=int(failed_recent or 0),
        oldest_queued_at=oldest,
        oldest_queued_age_seconds=_age(now, oldest),
    )


async def _webhooks(session: AsyncSession, now: datetime, since: datetime) -> WebhookStats:
    by_state = await _count_by(session, WebhookDelivery.state)
    failed_recent = await session.scalar(
        select(func.count()).where(
            WebhookDelivery.state.in_(_WEBHOOK_TERMINAL), WebhookDelivery.updated_at >= since
        )
    )
    pending = WebhookDelivery.state.in_(_WEBHOOK_PENDING)
    oldest = await session.scalar(select(func.min(WebhookDelivery.created_at)).where(pending))
    due = func.coalesce(WebhookDelivery.next_attempt_at, WebhookDelivery.created_at)
    earliest_due = await session.scalar(select(func.min(due)).where(and_(pending, due <= now)))
    return WebhookStats(
        by_state=by_state,
        failed_recent=int(failed_recent or 0),
        oldest_pending_at=oldest,
        oldest_pending_age_seconds=_age(now, oldest),
        max_overdue_seconds=_age(now, earliest_due),
    )


def _max_update_status_column() -> InstrumentedAttribute[Any] | None:
    for name in ("state", "status"):
        column = getattr(MaxUpdate, name, None)
        if isinstance(column, InstrumentedAttribute):
            return column
    return None


async def _max_updates(session: AsyncSession, now: datetime, since: datetime) -> MaxUpdateStats:
    last_received = await session.scalar(select(func.max(MaxUpdate.received_at)))
    column = _max_update_status_column()
    if column is not None:
        by_state = await _count_by(session, column)
        dead_recent = await session.scalar(
            select(func.count()).where(column.in_(_MAX_UPDATE_DEAD), MaxUpdate.received_at >= since)
        )
        oldest = await session.scalar(
            select(func.min(MaxUpdate.received_at)).where(column.in_(_MAX_UPDATE_PENDING))
        )
        source = column.key
    else:
        failed = MaxUpdate.processing_error.is_not(None)
        unprocessed = and_(MaxUpdate.processed_at.is_(None), ~failed)
        total_failed = await session.scalar(select(func.count()).where(failed))
        total_unprocessed = await session.scalar(select(func.count()).where(unprocessed))
        by_state = {"failed": int(total_failed or 0), "unprocessed": int(total_unprocessed or 0)}
        dead_recent = await session.scalar(
            select(func.count()).where(failed, MaxUpdate.received_at >= since)
        )
        oldest = await session.scalar(select(func.min(MaxUpdate.received_at)).where(unprocessed))
        source = "processing_error"
    return MaxUpdateStats(
        by_state=by_state,
        dead_recent=int(dead_recent or 0),
        oldest_pending_age_seconds=_age(now, oldest),
        last_received_at=last_received,
        source=source,
    )


def _subscription(settings: Settings, heartbeats: Sequence[LoopHeartbeat]) -> SubscriptionStats:
    beat = next((b for b in heartbeats if b.name == BOT_SUBSCRIPTION_LOOP), None)
    return SubscriptionStats(
        mode=settings.max_updates_mode,
        checked=beat is not None and not beat.missing,
        last_checked_at=beat.last_success_at if beat else None,
        last_error_at=beat.last_error_at if beat else None,
        last_error=beat.last_error if beat else None,
        failing=beat.failing if beat else False,
    )


def evaluate_alarms(
    settings: Settings,
    heartbeats: Sequence[LoopHeartbeat],
    notifications: NotificationStats,
    webhooks: WebhookStats,
    max_updates: MaxUpdateStats,
    subscription: SubscriptionStats,
) -> list[Alarm]:
    alarms: list[Alarm] = []
    if not heartbeats:
        alarms.append(Alarm("worker_heartbeat_missing", "worker не записал ни одного heartbeat"))
    for beat in heartbeats:
        if beat.stale:
            alarms.append(
                Alarm(
                    "worker_loop_stale",
                    f"цикл {beat.name} не завершал проход успешно дольше порога",
                    {
                        "loop": beat.name,
                        "age_seconds": _round(beat.age_seconds),
                        "threshold_seconds": beat.stale_after_seconds,
                    },
                )
            )
        elif beat.failing and beat.consecutive_failures >= settings.ops_loop_failures_max:
            alarms.append(
                Alarm(
                    "worker_loop_failing",
                    f"цикл {beat.name} падает подряд",
                    {
                        "loop": beat.name,
                        "consecutive_failures": beat.consecutive_failures,
                        "error": beat.last_error,
                    },
                )
            )
    age = notifications.oldest_queued_age_seconds
    if age is not None and age > settings.ops_notification_max_age_seconds:
        alarms.append(
            Alarm(
                "notification_backlog_stale",
                "уведомление ждёт отправки дольше порога",
                {
                    "age_seconds": _round(age),
                    "threshold_seconds": settings.ops_notification_max_age_seconds,
                },
            )
        )
    if notifications.failed_recent > settings.ops_notification_failed_max:
        alarms.append(
            Alarm(
                "notification_failed",
                "много неотправленных уведомлений за окно",
                {
                    "count": notifications.failed_recent,
                    "threshold": settings.ops_notification_failed_max,
                    "window_seconds": settings.ops_failed_window_seconds,
                },
            )
        )
    overdue = webhooks.max_overdue_seconds
    if overdue is not None and overdue > settings.ops_webhook_overdue_max_seconds:
        alarms.append(
            Alarm(
                "webhook_backlog_stale",
                "вебхук ждёт попытки доставки дольше порога",
                {
                    "overdue_seconds": _round(overdue),
                    "threshold_seconds": settings.ops_webhook_overdue_max_seconds,
                },
            )
        )
    if webhooks.failed_recent > settings.ops_webhook_failed_max:
        alarms.append(
            Alarm(
                "webhook_failed",
                "много вебхуков без дальнейших попыток за окно",
                {
                    "count": webhooks.failed_recent,
                    "threshold": settings.ops_webhook_failed_max,
                    "window_seconds": settings.ops_failed_window_seconds,
                },
            )
        )
    if max_updates.dead_recent > settings.ops_max_updates_failed_max:
        alarms.append(
            Alarm(
                "max_updates_failed",
                "входящие события MAX не обработаны и больше не повторяются",
                {
                    "count": max_updates.dead_recent,
                    "threshold": settings.ops_max_updates_failed_max,
                    "window_seconds": settings.ops_failed_window_seconds,
                },
            )
        )
    if subscription.mode == "webhook" and subscription.failing:
        alarms.append(
            Alarm(
                "max_subscription_failing",
                "последняя проверка подписки MAX завершилась ошибкой",
                {"error": subscription.last_error},
            )
        )
    return alarms


async def collect_status(now: datetime, settings: Settings) -> OpsStatus:
    heartbeats = await load_heartbeats(now)
    since = now - timedelta(seconds=settings.ops_failed_window_seconds)
    async with db_session.transaction() as session:
        notifications = await _notifications(session, now, since)
        webhooks = await _webhooks(session, now, since)
        max_updates = await _max_updates(session, now, since)
    subscription = _subscription(settings, heartbeats)
    return OpsStatus(
        checked_at=now,
        heartbeats=heartbeats,
        notifications=notifications,
        webhooks=webhooks,
        max_updates=max_updates,
        max_subscription=subscription,
        alarms=evaluate_alarms(
            settings, heartbeats, notifications, webhooks, max_updates, subscription
        ),
    )


def render_prometheus(status: OpsStatus) -> str:
    """Тот же срез в текстовом формате Prometheus (без клиентской библиотеки)."""
    lines: list[str] = []

    def metric(name: str, kind: str, help_text: str, samples: list[tuple[str, float]]) -> None:
        lines.append(f"# HELP repair_hub_{name} {help_text}")
        lines.append(f"# TYPE repair_hub_{name} {kind}")
        for labels, value in samples:
            lines.append(f"repair_hub_{name}{labels} {value:g}")

    def label(**pairs: str) -> str:
        inner = ",".join(f'{key}="{_escape(value)}"' for key, value in pairs.items())
        return "{" + inner + "}"

    metric("ops_degraded", "gauge", "1, если есть причины degraded", [("", float(status.degraded))])
    metric(
        "ops_alarm",
        "gauge",
        "Активные причины degraded по коду",
        [(label(code=code), 1.0) for code in sorted({a.code for a in status.alarms})],
    )
    metric(
        "worker_loop_age_seconds",
        "gauge",
        "Секунд с последнего успешного прохода цикла",
        [
            (label(loop=b.name), b.age_seconds if b.age_seconds is not None else -1.0)
            for b in status.heartbeats
        ],
    )
    metric(
        "worker_loop_stale",
        "gauge",
        "1, если цикл не отчитывался дольше порога",
        [(label(loop=b.name), float(b.stale)) for b in status.heartbeats],
    )
    metric(
        "worker_loop_consecutive_failures",
        "gauge",
        "Подряд неудачных проходов цикла",
        [(label(loop=b.name), float(b.consecutive_failures)) for b in status.heartbeats],
    )
    metric(
        "notifications",
        "gauge",
        "Уведомления по состоянию",
        [(label(state=s), float(c)) for s, c in sorted(status.notifications.by_state.items())],
    )
    metric(
        "notifications_oldest_pending_age_seconds",
        "gauge",
        "Возраст самого старого ожидающего уведомления",
        [("", status.notifications.oldest_queued_age_seconds or 0.0)],
    )
    metric(
        "webhook_deliveries",
        "gauge",
        "Доставки вебхуков по состоянию",
        [(label(state=s), float(c)) for s, c in sorted(status.webhooks.by_state.items())],
    )
    metric(
        "webhook_oldest_pending_age_seconds",
        "gauge",
        "Возраст самой старой ожидающей доставки вебхука",
        [("", status.webhooks.oldest_pending_age_seconds or 0.0)],
    )
    metric(
        "webhook_max_overdue_seconds",
        "gauge",
        "Наибольшая просрочка попытки доставки вебхука",
        [("", status.webhooks.max_overdue_seconds or 0.0)],
    )
    metric(
        "max_updates",
        "gauge",
        "Входящие события MAX по состоянию",
        [(label(state=s), float(c)) for s, c in sorted(status.max_updates.by_state.items())],
    )
    metric(
        "max_subscription_failing",
        "gauge",
        "1, если последняя проверка подписки MAX неуспешна",
        [("", float(status.max_subscription.failing))],
    )
    return "\n".join(lines) + "\n"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
