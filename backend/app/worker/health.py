import asyncio
import sys

from app.core.clock import utcnow
from app.db import session as db_session
from app.infra.config import Settings, get_settings
from app.modules.ops import api as ops
from app.worker.loops import build_loops


def required_loops(settings: Settings) -> dict[str, int]:
    return {
        loop.name: ops.stale_after_seconds(loop.interval_seconds, settings)
        for loop in build_loops(settings)
    }


async def check(settings: Settings) -> list[str]:
    beats = await ops.load_heartbeats(utcnow(), required_loops(settings))
    problems = []
    for beat in beats:
        if beat.missing:
            problems.append(f"{beat.name}: нет heartbeat")
        elif beat.stale:
            problems.append(
                f"{beat.name}: нет успешного прохода {beat.age_seconds or 0:.0f} с "
                f"(порог {beat.stale_after_seconds} с, последняя ошибка: {beat.last_error})"
            )
    return problems


async def main() -> int:
    try:
        problems = await check(get_settings())
    except Exception as exc:
        problems = [f"проверка не выполнена: {type(exc).__name__}"]
    finally:
        await db_session.dispose()
    for problem in problems:
        print(f"worker unhealthy: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
