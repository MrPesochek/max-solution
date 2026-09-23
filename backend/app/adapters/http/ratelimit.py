import time
from collections import deque
from collections.abc import Callable

from fastapi import Request

from app.core.errors import RateLimited
from app.infra.config import get_settings

_MAX_TRACKED = 10_000


class SlidingWindowLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    def hit(self, key: str, *, limit: int, window: float) -> bool:
        """Учитывает попытку. False — лимит окна исчерпан."""
        now = self._clock()
        hits = self._hits.get(key)
        if hits is None:
            if len(self._hits) >= _MAX_TRACKED:
                self._evict(now, window)
            hits = self._hits[key] = deque()
        while hits and hits[0] <= now - window:
            hits.popleft()
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True

    def reset(self) -> None:
        self._hits.clear()

    def _evict(self, now: float, window: float) -> None:
        stale = [key for key, hits in self._hits.items() if not hits or hits[-1] <= now - window]
        for key in stale:
            del self._hits[key]
        while len(self._hits) >= _MAX_TRACKED:
            del self._hits[next(iter(self._hits))]


auth_limiter = SlidingWindowLimiter()
provider_search_limiter = SlidingWindowLimiter()
PROVIDER_SEARCH_LIMIT = 30
PROVIDER_SEARCH_WINDOW_SECONDS = 60.0
access_request_limiter = SlidingWindowLimiter()
ACCESS_REQUEST_LIMIT = 5
ACCESS_REQUEST_WINDOW_SECONDS = 3600.0


def client_ip(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


async def limit_auth_attempts(request: Request) -> None:
    settings = get_settings()
    allowed = auth_limiter.hit(
        client_ip(request),
        limit=settings.auth_rate_limit_attempts,
        window=settings.auth_rate_limit_window_seconds,
    )
    if not allowed:
        raise RateLimited(retry_after_seconds=settings.auth_rate_limit_window_seconds)


def limit_provider_search(session_key: str) -> None:
    if not provider_search_limiter.hit(
        session_key, limit=PROVIDER_SEARCH_LIMIT, window=PROVIDER_SEARCH_WINDOW_SECONDS
    ):
        raise RateLimited(retry_after_seconds=int(PROVIDER_SEARCH_WINDOW_SECONDS))


def limit_access_requests(membership_key: str) -> None:
    if not access_request_limiter.hit(
        membership_key, limit=ACCESS_REQUEST_LIMIT, window=ACCESS_REQUEST_WINDOW_SECONDS
    ):
        raise RateLimited(retry_after_seconds=int(ACCESS_REQUEST_WINDOW_SECONDS))
