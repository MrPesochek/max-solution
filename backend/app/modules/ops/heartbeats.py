import math
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app.db import session as db_session
from app.db.models import WorkerHeartbeat
from app.infra.config import Settings

_OK = "ok"
_ERROR = "error"


def stale_after_seconds(interval_seconds: float, settings: Settings) -> int:
    """Порог «цикл завис»: без успешного прохода дольше этого — сбой."""
    return math.ceil(
        interval_seconds * settings.worker_heartbeat_interval_multiplier
        + settings.worker_heartbeat_grace_seconds
        + settings.worker_heartbeat_write_seconds
    )


@dataclass(frozen=True, slots=True)
class LoopHeartbeat:
    name: str
    stale_after_seconds: int
    registered_at: datetime | None
    last_success_at: datetime | None
    last_processed: int | None
    last_error_at: datetime | None
    last_error: str | None
    consecutive_failures: int
    age_seconds: float | None
    stale: bool
    missing: bool = False

    @property
    def failing(self) -> bool:
        """Последний записанный проход закончился ошибкой."""
        if self.last_error_at is None:
            return False
        return self.last_success_at is None or self.last_error_at > self.last_success_at


def _evaluate(row: WorkerHeartbeat, now: datetime, threshold: int) -> LoopHeartbeat:
    marks = [mark for mark in (row.last_success_at, row.registered_at) if mark is not None]
    reference = max(marks) if marks else None
    age = (now - reference).total_seconds() if reference is not None else None
    return LoopHeartbeat(
        name=row.loop_name,
        stale_after_seconds=threshold,
        registered_at=row.registered_at,
        last_success_at=row.last_success_at,
        last_processed=row.last_processed,
        last_error_at=row.last_error_at,
        last_error=row.last_error,
        consecutive_failures=row.consecutive_failures,
        age_seconds=age,
        stale=age is None or age > threshold,
    )


def _missing(name: str, threshold: int) -> LoopHeartbeat:
    return LoopHeartbeat(
        name=name,
        stale_after_seconds=threshold,
        registered_at=None,
        last_success_at=None,
        last_processed=None,
        last_error_at=None,
        last_error=None,
        consecutive_failures=0,
        age_seconds=None,
        stale=True,
        missing=True,
    )


async def load_heartbeats(
    now: datetime, required: Mapping[str, int] | None = None
) -> list[LoopHeartbeat]:
    """Состояние циклов на момент `now`.

    `required` — обязательные циклы и их пороги (healthcheck считает их из своих
    настроек): отсутствующая строка — сбой, порог берётся из `required`. Без него —
    все записанные строки с порогом, который записал worker.
    """
    async with db_session.transaction() as session:
        rows = {
            row.loop_name: row for row in (await session.execute(select(WorkerHeartbeat))).scalars()
        }
    if required is None:
        return [_evaluate(row, now, row.stale_after_seconds) for _, row in sorted(rows.items())]
    result: list[LoopHeartbeat] = []
    for name, threshold in required.items():
        row = rows.get(name)
        result.append(_missing(name, threshold) if row is None else _evaluate(row, now, threshold))
    return result


@dataclass(slots=True)
class HeartbeatWriter:
    """Пишет heartbeat циклов. Ошибку записи вызывающий только журналирует: без БД
    цикл всё равно не работает, а healthcheck увидит отсутствие свежей строки."""

    thresholds: dict[str, int]
    write_seconds: float
    _written_at: dict[str, float] = field(default_factory=dict)
    _outcome: dict[str, str] = field(default_factory=dict)
    _failures: dict[str, int] = field(default_factory=dict)

    @classmethod
    def for_loops(cls, intervals: Mapping[str, float], settings: Settings) -> "HeartbeatWriter":
        return cls(
            thresholds={
                name: stale_after_seconds(interval, settings)
                for name, interval in intervals.items()
            },
            write_seconds=settings.worker_heartbeat_write_seconds,
        )

    async def register(self, now: datetime) -> None:
        """Старт процесса: строки текущих циклов, строки снятых с реестра — удаляются
        (иначе цикл, выключенный настройкой, навсегда считался бы зависшим)."""
        async with db_session.transaction() as session:
            await session.execute(
                delete(WorkerHeartbeat).where(
                    WorkerHeartbeat.loop_name.not_in(list(self.thresholds))
                )
            )
            for name, threshold in self.thresholds.items():
                statement = insert(WorkerHeartbeat).values(
                    loop_name=name, stale_after_seconds=threshold, registered_at=now
                )
                await session.execute(
                    statement.on_conflict_do_update(
                        index_elements=[WorkerHeartbeat.loop_name],
                        set_={
                            "stale_after_seconds": statement.excluded.stale_after_seconds,
                            "registered_at": statement.excluded.registered_at,
                            "consecutive_failures": 0,
                            "updated_at": now,
                        },
                    )
                )

    def _due(self, name: str, outcome: str) -> bool:
        previous = self._outcome.get(name)
        written = self._written_at.get(name)
        if previous != outcome or written is None:
            return True
        return time.monotonic() - written >= self.write_seconds

    def _mark(self, name: str, outcome: str) -> None:
        self._outcome[name] = outcome
        self._written_at[name] = time.monotonic()

    async def succeeded(self, loop: str, now: datetime, processed: int) -> None:
        self._failures[loop] = 0
        if not self._due(loop, _OK):
            return
        await self._upsert(
            loop,
            now,
            {"last_success_at": now, "last_processed": processed, "consecutive_failures": 0},
        )
        self._mark(loop, _OK)

    async def failed(self, loop: str, now: datetime, error: BaseException) -> None:
        failures = self._failures.get(loop, 0) + 1
        self._failures[loop] = failures
        if not self._due(loop, _ERROR):
            return
        await self._upsert(
            loop,
            now,
            {
                "last_error_at": now,
                "last_error": type(error).__name__,
                "consecutive_failures": failures,
            },
        )
        self._mark(loop, _ERROR)

    async def _upsert(self, loop: str, now: datetime, values: dict[str, object]) -> None:
        threshold = self.thresholds.get(loop)
        if threshold is None:
            return
        statement = insert(WorkerHeartbeat).values(
            loop_name=loop, stale_after_seconds=threshold, registered_at=now, **values
        )
        async with db_session.transaction() as session:
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[WorkerHeartbeat.loop_name],
                    set_={**values, "updated_at": now},
                )
            )
