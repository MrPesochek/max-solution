import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.modules.requests import api as requests
from app.worker import request_sweeper

pytestmark = pytest.mark.asyncio


async def test_run_once_sums_counters(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_expire_due(now: object) -> dict[str, int]:
        return {"visit_proposals": 2, "repair_quotes": 0, "offers": 1}

    monkeypatch.setattr(requests, "expire_due", fake_expire_due)
    assert await request_sweeper.run_once(utcnow()) == 3


async def test_run_once_against_empty_database(db_session: AsyncSession) -> None:
    assert await request_sweeper.run_once(utcnow()) == 0
