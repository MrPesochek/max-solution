import asyncio
from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WorkerHeartbeat
from app.infra.config import Settings
from app.modules.ops import api as ops
from app.worker import health
from app.worker.runner import Loop, run_loops
from tests.ops.conftest import Clock

pytestmark = pytest.mark.usefixtures("db_session")


async def _run_until(loops: list[Loop], writer: ops.HeartbeatWriter, done: asyncio.Event) -> None:
    stop = asyncio.Event()
    task = asyncio.create_task(run_loops(loops, stop, writer))
    await asyncio.wait_for(done.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_hung_loop_fails_health_while_working_loop_passes(
    settings: Settings, clock: Clock
) -> None:
    hang = asyncio.Event()
    good_runs = 0
    done = asyncio.Event()

    async def hung(now: datetime) -> int:
        await hang.wait()
        return 0

    async def good(now: datetime) -> int:
        nonlocal good_runs
        good_runs += 1
        if good_runs >= 3:
            done.set()
        return 1

    writer = ops.HeartbeatWriter.for_loops({"hung": 1.0, "good": 1.0}, settings)
    await writer.register(clock.now)
    clock.advance(60)
    await _run_until([Loop("hung", hung, 0.001), Loop("good", good, 0.001)], writer, done)

    required = {"hung": ops.stale_after_seconds(1.0, settings), "good": 6}
    beats = {beat.name: beat for beat in await ops.load_heartbeats(clock.now, required)}
    assert beats["good"].stale is False
    assert beats["good"].last_processed == 1
    assert beats["hung"].stale is True
    assert beats["hung"].last_success_at is None
    assert beats["hung"].age_seconds == pytest.approx(60)


async def _register_registry(settings: Settings, now: datetime) -> ops.HeartbeatWriter:
    writer = ops.HeartbeatWriter(thresholds=health.required_loops(settings), write_seconds=0)
    await writer.register(now)
    return writer


async def test_health_passes_when_every_registry_loop_reported(
    settings: Settings, clock: Clock
) -> None:
    writer = await _register_registry(settings, clock.now)
    clock.advance(4 * 3600)
    for name in writer.thresholds:
        await writer.succeeded(name, clock.now, 0)

    assert await health.check(settings) == []


async def test_health_fails_on_stale_registry_loop(settings: Settings, clock: Clock) -> None:
    writer = await _register_registry(settings, clock.now)
    clock.advance(4 * 3600)
    for name in writer.thresholds:
        if name != "notification_dispatcher":
            await writer.succeeded(name, clock.now, 0)

    problems = await health.check(settings)
    assert len(problems) == 1
    assert problems[0].startswith("notification_dispatcher: нет успешного прохода")


async def test_health_fails_on_missing_heartbeat_row(settings: Settings, clock: Clock) -> None:
    problems = await health.check(settings)
    assert "notification_dispatcher: нет heartbeat" in problems


async def test_constantly_failing_loop_goes_stale_and_recovers_after_success(
    settings: Settings, clock: Clock
) -> None:
    writer = await _register_registry(settings, clock.now)
    clock.advance(4 * 3600)
    for name in writer.thresholds:
        if name != "webhook_dispatcher":
            await writer.succeeded(name, clock.now, 0)
    for _ in range(3):
        await writer.failed("webhook_dispatcher", clock.now, RuntimeError("CRM"))

    problems = await health.check(settings)
    assert len(problems) == 1
    assert "webhook_dispatcher" in problems[0]
    assert "RuntimeError" in problems[0]

    await writer.succeeded("webhook_dispatcher", clock.now, 2)
    assert await health.check(settings) == []


async def test_runner_records_failures_without_stopping(
    settings: Settings, clock: Clock, db_session: AsyncSession
) -> None:
    calls = 0
    done = asyncio.Event()

    async def flaky(now: datetime) -> int:
        nonlocal calls
        calls += 1
        if calls >= 4:
            done.set()
        raise ValueError("сбой")

    writer = ops.HeartbeatWriter.for_loops({"flaky": 1.0}, settings)
    await writer.register(clock.now)
    stop = asyncio.Event()
    task = asyncio.create_task(run_loops([Loop("flaky", flaky, 0.001)], stop, writer))
    await asyncio.wait_for(done.wait(), timeout=5)
    stop.set()
    await asyncio.wait_for(task, timeout=5)

    row = await db_session.scalar(
        select(WorkerHeartbeat).where(WorkerHeartbeat.loop_name == "flaky")
    )
    assert row is not None
    assert row.last_success_at is None
    assert row.last_error == "ValueError"
    assert row.consecutive_failures >= 4


async def test_heartbeat_write_failure_does_not_stop_loop(clock: Clock) -> None:
    class BrokenHeartbeat:
        async def succeeded(self, loop: str, now: datetime, processed: int) -> None:
            raise ConnectionError("БД недоступна")

        async def failed(self, loop: str, now: datetime, error: BaseException) -> None:
            raise ConnectionError("БД недоступна")

    calls = 0
    stop = asyncio.Event()

    async def counting(now: datetime) -> int:
        nonlocal calls
        calls += 1
        if calls >= 3:
            stop.set()
        return 1

    await asyncio.wait_for(
        run_loops([Loop("counting", counting, 0.001)], stop, BrokenHeartbeat()), timeout=5
    )
    assert calls >= 3


async def test_register_drops_loops_removed_from_registry(
    settings: Settings, clock: Clock, db_session: AsyncSession
) -> None:
    old = ops.HeartbeatWriter.for_loops({"bot_subscription": 900.0, "cleanup": 3600.0}, settings)
    await old.register(clock.now)
    new = ops.HeartbeatWriter.for_loops({"cleanup": 3600.0}, settings)
    await new.register(clock.now)

    names = set((await db_session.execute(select(WorkerHeartbeat.loop_name))).scalars())
    assert names == {"cleanup"}


async def test_heartbeat_writes_are_throttled(settings: Settings, clock: Clock) -> None:
    writer = ops.HeartbeatWriter(thresholds={"fast": 10}, write_seconds=3600)
    await writer.register(clock.now)
    await writer.succeeded("fast", clock.now, 1)
    first = clock.now
    clock.advance(5)
    await writer.succeeded("fast", clock.now, 1)
    beats = await ops.load_heartbeats(clock.now)
    assert beats[0].last_success_at == first
    await writer.failed("fast", clock.now, RuntimeError())
    beats = await ops.load_heartbeats(clock.now)
    assert beats[0].last_error_at == clock.now
    assert beats[0].failing is True


async def test_health_main_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    async def failing_check(settings: Settings) -> list[str]:
        return ["cleanup: нет heartbeat"]

    async def passing_check(settings: Settings) -> list[str]:
        return []

    async def no_dispose() -> None:
        return None

    monkeypatch.setattr(health.db_session, "dispose", no_dispose)
    monkeypatch.setattr(health, "check", failing_check)
    assert await health.main() == 1
    monkeypatch.setattr(health, "check", passing_check)
    assert await health.main() == 0
