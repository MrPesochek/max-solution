from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.bot import texts
from app.db.models import RepairRequest
from tests.bot import flows
from tests.bot import requests_factories as rf
from tests.bot.conftest import BotHarness


async def test_resume_continues_same_draft(harness: BotHarness, db_session: AsyncSession) -> None:
    world = await rf.build(db_session)
    await db_session.commit()
    uid = int(world.employee_max_id)

    await flows.say(harness, "/start", uid)
    await flows.open_menu(harness, "my_service", uid)
    await flows.press(harness, harness.payload_of("Кафе на Ленина"), uid)
    await flows.press(harness, harness.payload_of("Полюс ВХС-1"), uid)
    await flows.say(harness, "/cancel", uid)

    await flows.open_menu(harness, "my_service", uid)
    await flows.press(harness, harness.payload_of(texts.RESUME_CONTINUE), uid)
    assert harness.last_text == texts.ASK_SYMPTOMS
    await flows.say(harness, "Течёт вода", uid)
    assert harness.last_text == texts.ASK_ERROR_CODE

    drafts = (await db_session.execute(select(RepairRequest))).scalars().all()
    assert len(drafts) == 1
    await db_session.refresh(drafts[0])
    assert drafts[0].symptom_description == "Течёт вода"
