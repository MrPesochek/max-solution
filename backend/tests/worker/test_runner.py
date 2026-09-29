import asyncio
from datetime import datetime

import pytest

from app.infra.config import Settings
from app.worker.loops import build_loops
from app.worker.runner import Loop, run_loops

pytestmark = pytest.mark.asyncio


async def test_stop_waits_for_current_iteration() -> None:
    started = asyncio.Event()
    finished = False

    async def slow(now: datetime) -> int:
        nonlocal finished
        started.set()
        await asyncio.sleep(0.05)
        finished = True
        return 1

    stop = asyncio.Event()
    task = asyncio.create_task(run_loops([Loop("slow", slow, 0.01)], stop))
    await started.wait()
    stop.set()
    await asyncio.wait_for(task, timeout=2)

    assert finished is True


async def test_failing_loop_does_not_stop_the_others() -> None:
    calls = {"bad": 0, "good": 0}
    stop = asyncio.Event()

    async def bad(now: datetime) -> int:
        calls["bad"] += 1
        raise RuntimeError("цикл упал")

    async def good(now: datetime) -> int:
        calls["good"] += 1
        if calls["good"] >= 3:
            stop.set()
        return 0

    await asyncio.wait_for(
        run_loops([Loop("bad", bad, 0.001), Loop("good", good, 0.001)], stop), timeout=2
    )
    assert calls["good"] >= 3
    assert calls["bad"] >= 1


async def test_registry_lists_all_loops() -> None:
    names = [loop.name for loop in build_loops(Settings())]
    assert {"feed_dispatcher", "webhook_dispatcher", "notification_dispatcher", "cleanup"}.issubset(
        set(names)
    )
    assert "request_sweeper" in names
    assert "bot_subscription" not in names


async def test_registry_adds_bot_subscription_loop_in_webhook_mode() -> None:
    names = [
        loop.name
        for loop in build_loops(
            Settings(max_updates_mode="webhook", max_bot_token="t", demo_login_enabled=False)
        )
    ]
    assert "bot_subscription" in names


async def test_registry_skips_bot_subscription_loop_off_mode() -> None:
    names = [loop.name for loop in build_loops(Settings(max_updates_mode="off"))]
    assert "bot_subscription" not in names
