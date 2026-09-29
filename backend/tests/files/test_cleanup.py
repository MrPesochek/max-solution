import uuid

import pytest
from sqlalchemy import update

from app.core.clock import utcnow
from app.db import session as db_session
from app.db.models import Attachment
from app.infra.storage.base import make_storage_key
from app.modules.files import api as files
from app.modules.files.storage import get_storage
from tests.files import helpers
from tests.requests import helpers as request_helpers
from tests.requests.factories import World

pytestmark = pytest.mark.usefixtures("clean_db")


async def _uploaded(world: World) -> uuid.UUID:
    draft = await request_helpers.make_draft(world)
    result = await helpers.upload(
        world.employee, files.request_owner(request_helpers.rid(draft)), helpers.png()
    )
    return helpers.aid(result.body)


async def test_old_orphan_key_is_removed(world: World) -> None:
    await _uploaded(world)
    await helpers.process()
    storage = get_storage()
    orphan_key = f"requests/2020/01/01/{uuid.uuid4().hex}"
    await storage.put(orphan_key, b"leftover")

    assert await files.cleanup_files(utcnow()) == 1
    assert not await storage.exists(orphan_key)


async def test_recent_orphan_key_is_kept(world: World) -> None:
    await _uploaded(world)
    await helpers.process()
    storage = get_storage()
    fresh_orphan = make_storage_key("requests")
    await storage.put(fresh_orphan, b"leftover")

    assert await files.cleanup_files(utcnow()) == 0
    assert await storage.exists(fresh_orphan)


async def test_referenced_key_is_kept_even_if_dated_old(world: World) -> None:
    attachment_id = await _uploaded(world)
    await helpers.process()
    storage = get_storage()

    old_key = f"requests/2020/01/01/{uuid.uuid4().hex}"
    orphan_key = f"requests/2020/01/01/{uuid.uuid4().hex}"
    await storage.put(old_key, b"kept")
    await storage.put(orphan_key, b"gone")
    async with db_session.transaction() as session:
        await session.execute(
            update(Attachment).where(Attachment.id == attachment_id).values(storage_key=old_key)
        )

    assert await files.cleanup_files(utcnow()) == 1
    assert await storage.exists(old_key)
    assert not await storage.exists(orphan_key)
