import pytest
from sqlalchemy import update

from app.core.errors import Conflict
from app.db import session as db_session
from app.db.models import ProviderProfile, VerificationCase
from app.modules.files import api as files
from app.modules.requests import api as requests_api
from tests.files import helpers
from tests.requests import helpers as request_helpers
from tests.requests.factories import World

pytestmark = pytest.mark.usefixtures("clean_db")


async def _case(world: World) -> VerificationCase:
    async with db_session.transaction() as session:
        case = VerificationCase(
            organization_id=world.customer_org_id,
            membership_id=world.manager.membership_id,
            subject_type="customer_representative",
            check_kind="customer_representative",
            decision="pending",
        )
        session.add(case)
        await session.flush()
        return case


async def _decide(case: VerificationCase, decision: str) -> None:
    async with db_session.transaction() as session:
        await session.execute(
            update(VerificationCase).where(VerificationCase.id == case.id).values(decision=decision)
        )


async def test_evidence_is_deletable_until_decision(world: World) -> None:
    case = await _case(world)
    owner = files.verification_owner(case.id)
    first = await helpers.upload(world.manager, owner, helpers.png())
    deleted = await files.delete_attachment(world.manager, helpers.aid(first.body))
    assert deleted.body["deleted"] is True

    second = await helpers.upload(world.manager, owner, helpers.png())
    await _decide(case, "approved")
    with pytest.raises(Conflict) as exc:
        await files.delete_attachment(world.manager, helpers.aid(second.body))
    assert exc.value.code == "ATTACHMENT_NOT_DELETABLE"
    assert (await helpers.attachment(helpers.aid(second.body))) is not None


async def _suspend(world: World) -> None:
    async with db_session.transaction() as session:
        await session.execute(
            update(ProviderProfile)
            .where(ProviderProfile.organization_id == world.provider_org_id)
            .values(status="suspended")
        )


async def test_suspended_provider_uploads_only_into_accepted_thread(world: World) -> None:
    accepted = await request_helpers.make_accepted(world)
    request_id = request_helpers.rid(accepted)
    message = (
        await requests_api.post_message(
            world.dispatcher,
            request_id,
            body="Фото шильдика",
            assignment_id=request_helpers.assignment_id(accepted),
        )
    ).body
    await _suspend(world)

    for actor in (world.dispatcher, world.integration):
        with pytest.raises(Conflict) as exc:
            await helpers.upload(actor, files.request_owner(request_id), helpers.png())
        assert exc.value.code == "PROVIDER_NOT_ACTIVE"

    from app.core import ids

    attached = await helpers.upload(
        world.dispatcher,
        files.message_owner(ids.decode("message", message["id"])),
        helpers.png(),
    )
    assert attached.status == 201


async def test_customer_of_suspended_provider_still_uploads(world: World) -> None:
    accepted = await request_helpers.make_accepted(world)
    await _suspend(world)
    result = await helpers.upload(
        world.employee, files.request_owner(request_helpers.rid(accepted)), helpers.png()
    )
    assert result.status == 201
