from app.infra.max.throttle import MaxThrottle


class FakeClock:
    """Управляемое время: sleep не ждёт по-настоящему, а сразу продвигает часы."""

    def __init__(self, start: float = 0.0) -> None:
        self.t = start
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    async def sleep(self, delay: float) -> None:
        self.sleeps.append(delay)
        self.t += delay


async def test_per_chat_limit_spaces_out_messages() -> None:
    clock = FakeClock()
    throttle = MaxThrottle(per_chat_rps=2.0, global_rps=100.0, clock=clock)

    await throttle.acquire(chat_id=1)
    assert clock.t == 0.0
    await throttle.acquire(chat_id=1)
    assert clock.t == 0.5
    await throttle.acquire(chat_id=1)
    assert clock.t == 1.0


async def test_different_chats_do_not_block_each_other_beyond_global_limit() -> None:
    clock = FakeClock()
    throttle = MaxThrottle(per_chat_rps=2.0, global_rps=100.0, clock=clock)

    await throttle.acquire(chat_id=1)
    await throttle.acquire(chat_id=2)
    assert clock.t == 1 / 100


async def test_global_limit_applies_across_chats() -> None:
    clock = FakeClock()
    throttle = MaxThrottle(per_chat_rps=100.0, global_rps=2.0, clock=clock)

    await throttle.acquire(chat_id=1)
    await throttle.acquire(chat_id=2)
    await throttle.acquire(chat_id=3)
    assert clock.t == 1.0


async def test_already_elapsed_time_needs_no_wait() -> None:
    clock = FakeClock()
    throttle = MaxThrottle(per_chat_rps=2.0, global_rps=100.0, clock=clock)
    await throttle.acquire(chat_id=1)
    clock.t += 10
    await throttle.acquire(chat_id=1)
    assert clock.sleeps == [] or clock.sleeps[-1] == 0
