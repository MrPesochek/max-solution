from collections.abc import Iterator
from pathlib import Path

import pytest

from app.core.errors import ValidationFailed
from app.infra.config import get_settings
from app.infra.storage.local import LocalFileStorage
from app.modules.files import api as files
from app.modules.reputation import api as reputation
from tests.files import helpers
from tests.requests import helpers as h
from tests.requests.factories import World
from tests.support import idem

pytestmark = pytest.mark.usefixtures("clean_db")


@pytest.fixture(autouse=True)
def storage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    monkeypatch.setenv("FILE_STORAGE_PATH", str(tmp_path / "files"))
    get_settings.cache_clear()
    files.set_storage(LocalFileStorage(tmp_path / "files"))
    yield
    files.set_storage(None)


async def test_nameplate_photo_needs_confirmation_in_review(world: World) -> None:
    completed = await h.make_completion_reported(world)
    photo = await helpers.upload(
        world.employee, files.request_owner(h.rid(completed)), helpers.png(), slot="nameplate"
    )
    await helpers.process()
    photo_id = helpers.aid(photo.body)

    with pytest.raises(ValidationFailed) as exc:
        await reputation.submit_review(
            world.manager,
            h.rid(completed),
            reputation.ReviewSubmitData(rating=5, photo_attachment_ids=[photo_id]),
            idem=idem("np-1"),
        )
    assert exc.value.code == "SENSITIVE_PHOTO_NOT_CONFIRMED"

    review = await reputation.submit_review(
        world.manager,
        h.rid(completed),
        reputation.ReviewSubmitData(
            rating=5, photo_attachment_ids=[photo_id], confirm_sensitive=True
        ),
        idem=idem("np-2"),
    )
    assert review.status == 201
    assert len(review.body["photo_attachment_ids"]) == 1
