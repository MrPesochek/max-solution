import pytest

from app.core.errors import ValidationFailed
from app.modules.files import api as files
from app.modules.requests import api as requests_api
from app.modules.requests.views import RequestCustomerView
from tests.files import helpers
from tests.requests import helpers as request_helpers
from tests.requests.factories import World

pytestmark = pytest.mark.usefixtures("clean_db")


async def test_report_lists_before_and_after_photos(world: World) -> None:
    in_progress = await request_helpers.make_in_progress(world)
    request_id = request_helpers.rid(in_progress)
    owner = files.request_owner(request_id)
    before = await helpers.upload(world.dispatcher, owner, helpers.png(), slot="before")
    after = await helpers.upload(world.integration, owner, helpers.png(), slot="after")
    await helpers.upload(world.dispatcher, owner, helpers.png())
    assert (before.body["slot"], after.body["slot"]) == ("before", "after")
    await helpers.process()

    reported = await requests_api.report_completion(
        world.dispatcher,
        request_id,
        assignment_id=request_helpers.assignment_id(in_progress),
        outcome="resolved",
        summary="Заменён термостат",
        expected_version=in_progress["version"],
    )
    report = reported.body["completion_report"]
    assert [p["id"] for p in report["photos_before"]] == [before.body["id"]]
    assert [p["id"] for p in report["photos_after"]] == [after.body["id"]]

    card = await requests_api.get_request(world.manager, request_id)
    assert isinstance(card, RequestCustomerView)
    assert card.completion_report is not None
    assert [p.id for p in card.completion_report.photos_before] == [before.body["id"]]
    assert [p.id for p in card.completion_report.photos_after] == [after.body["id"]]


async def test_customer_cannot_fill_report_slots(world: World) -> None:
    accepted = await request_helpers.make_accepted(world)
    owner = files.request_owner(request_helpers.rid(accepted))
    for slot in ("before", "after"):
        with pytest.raises(ValidationFailed):
            await helpers.upload(world.employee, owner, helpers.png(), slot=slot)
