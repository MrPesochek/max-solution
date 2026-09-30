import math
import time
from dataclasses import dataclass

from app.core.errors import RateLimited


@dataclass(slots=True)
class _Bucket:
    tokens: float
    updated_at: float


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    limit: int
    remaining: int
    reset_after: int


class RateLimitExceeded(RateLimited):
    default_message = "Превышен лимит запросов"

    def __init__(self, decision: Decision) -> None:
        super().__init__(retry_after=decision.reset_after)
        self.decision = decision


MAX_TRACKED = 10_000


class TokenBucketLimiter:
    def __init__(
        self, *, rate_per_second: float, burst: int, max_tracked: int = MAX_TRACKED
    ) -> None:
        if rate_per_second <= 0 or burst <= 0:
            raise ValueError("лимит должен быть положительным")
        self._rate = rate_per_second
        self._burst = burst
        self._max_tracked = max_tracked
        self._buckets: dict[str, _Bucket] = {}

    def check(self, key: str, *, now: float | None = None) -> Decision:
        moment = time.monotonic() if now is None else now
        bucket = self._buckets.get(key)
        if bucket is None:
            if len(self._buckets) >= self._max_tracked:
                self._evict(moment)
            bucket = _Bucket(tokens=float(self._burst), updated_at=moment)
            self._buckets[key] = bucket
        else:
            elapsed = max(0.0, moment - bucket.updated_at)
            bucket.tokens = min(float(self._burst), bucket.tokens + elapsed * self._rate)
            bucket.updated_at = moment

        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return Decision(
                allowed=True,
                limit=self._burst,
                remaining=int(bucket.tokens),
                reset_after=self._reset_after(bucket),
            )
        return Decision(
            allowed=False, limit=self._burst, remaining=0, reset_after=self._reset_after(bucket)
        )

    def peek(self, key: str, *, now: float | None = None) -> Decision:
        moment = time.monotonic() if now is None else now
        bucket = self._buckets.get(key)
        if bucket is None:
            return Decision(allowed=True, limit=self._burst, remaining=self._burst, reset_after=0)
        elapsed = max(0.0, moment - bucket.updated_at)
        tokens = min(float(self._burst), bucket.tokens + elapsed * self._rate)
        probe = _Bucket(tokens=tokens, updated_at=moment)
        return Decision(
            allowed=tokens >= 1.0,
            limit=self._burst,
            remaining=int(tokens),
            reset_after=self._reset_after(probe),
        )

    def refund(self, key: str) -> None:
        bucket = self._buckets.get(key)
        if bucket is not None:
            bucket.tokens = min(float(self._burst), bucket.tokens + 1.0)

    def _evict(self, moment: float) -> None:
        full = [
            key
            for key, bucket in self._buckets.items()
            if bucket.tokens + (moment - bucket.updated_at) * self._rate >= self._burst
        ]
        for key in full:
            del self._buckets[key]
        while len(self._buckets) >= self._max_tracked:
            del self._buckets[next(iter(self._buckets))]

    def __len__(self) -> int:
        return len(self._buckets)

    def _reset_after(self, bucket: _Bucket) -> int:
        missing = self._burst - bucket.tokens
        if missing <= 0:
            return 0
        return max(1, math.ceil(missing / self._rate))

    def reset(self) -> None:
        self._buckets.clear()


def headers_of(decision: Decision) -> dict[str, str]:
    return {
        "RateLimit-Limit": str(decision.limit),
        "RateLimit-Remaining": str(decision.remaining),
        "RateLimit-Reset": str(decision.reset_after),
    }
