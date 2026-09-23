import json
import random
from dataclasses import dataclass
from typing import Literal

import httpx

from app.infra.net.signing import sign_webhook
from app.infra.net.ssrf import PrivateHosts, SsrfValidationError, post_pinned
from app.modules.integration.views import EventEnvelopeView

Outcome = Literal["delivered", "retryable", "permanent", "blocked"]


@dataclass(frozen=True, slots=True)
class OutgoingWebhook:
    url: str
    secret: str
    event_id: str
    delivery_id: str
    body: bytes
    timestamp: int


@dataclass(frozen=True, slots=True)
class AttemptResult:
    outcome: Outcome
    status_code: int | None = None
    error: str | None = None

    @property
    def delivered(self) -> bool:
        return self.outcome == "delivered"


def build_body(envelope: EventEnvelopeView) -> bytes:
    payload = envelope.model_dump(mode="json")
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()


def build_headers(outgoing: OutgoingWebhook) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Event-ID": outgoing.event_id,
        "X-Delivery-ID": outgoing.delivery_id,
        "X-Timestamp": str(outgoing.timestamp),
        "X-Signature": sign_webhook(outgoing.secret.encode(), outgoing.timestamp, outgoing.body),
    }


async def deliver(
    outgoing: OutgoingWebhook,
    *,
    timeout: float,  # noqa: ASYNC109 — таймаут HTTP передаётся транспорту, не asyncio
    private_hosts: PrivateHosts = (),
) -> AttemptResult:
    try:
        response = await post_pinned(
            outgoing.url,
            body=outgoing.body,
            headers=build_headers(outgoing),
            timeout=timeout,
            private_hosts=private_hosts,
        )
    except SsrfValidationError as exc:
        return AttemptResult(outcome="blocked", error=f"ssrf:{exc.reason}")
    except httpx.TimeoutException:
        return AttemptResult(outcome="retryable", error="timeout")
    except httpx.HTTPError:
        return AttemptResult(outcome="retryable", error="network")

    status = response.status_code
    if 200 <= status < 300:
        return AttemptResult(outcome="delivered", status_code=status)
    if status == 429 or status >= 500:
        return AttemptResult(outcome="retryable", status_code=status, error=f"http:{status}")
    return AttemptResult(outcome="permanent", status_code=status, error=f"http:{status}")


def retry_delay(attempt: int, *, base: float, maximum: float) -> float:
    """Экспоненциальный бэкофф с разбросом; `attempt` — номер уже сделанной попытки."""
    span: float = min(base * float(2 ** max(0, attempt - 1)), maximum)
    return span / 2 + random.random() * (span / 2)  # noqa: S311 — джиттер, не криптография
