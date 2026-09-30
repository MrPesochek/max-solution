import pytest

from app.core import ids
from app.core.actor import UserActor
from app.core.errors import Unauthenticated
from app.demo import scenarios, seed
from app.infra.config import get_settings
from app.modules.files import api as files
from app.modules.identity.api import login_demo
from app.modules.providers.api import get_public_profile
from tests import factories

pytestmark = pytest.mark.usefixtures("clean_db")


async def test_seed_runs_on_clean_db() -> None:
    report = await seed.run()

    assert report.organizations == 10
    assert report.users == 13
    assert report.requests_created == len(scenarios.SCENARIOS)
    assert report.integration_client_created is True


async def test_seed_is_idempotent() -> None:
    await seed.run()
    report = await seed.run()

    assert report.organizations == 0
    assert report.users == 0
    assert report.requests_created == 0
    assert report.integration_client_created is False


@pytest.mark.parametrize("user_key", [k for k in seed.DEMO_USER_KEYS if k != "operator"])
async def test_demo_login_works_for_every_user_key(user_key: str) -> None:
    await seed.run()

    issued = await login_demo(user_key)

    assert issued.token


async def test_demo_operator_login_only_on_local_stand(monkeypatch: pytest.MonkeyPatch) -> None:
    await seed.run()
    with pytest.raises(Unauthenticated):
        await login_demo("operator")

    for _ in factories.apply_test_settings(monkeypatch, APP_ENV="local", MAX_BOT_TOKEN=""):
        assert (await login_demo("operator")).token


async def test_employee_sees_only_one_location() -> None:
    await seed.run()

    issued = await login_demo("employee")

    assert len(issued.memberships) == 1
    assert issued.memberships[0].role == "customer_employee"
    assert len(issued.memberships[0].location_ids) == 1


async def test_manager_sees_both_locations() -> None:
    await seed.run()

    issued = await login_demo("manager")

    assert len(issued.memberships) == 1
    assert issued.memberships[0].role == "customer_manager"
    assert issued.memberships[0].location_ids == []


async def test_reset_removes_only_demo_data() -> None:
    await seed.run()
    await seed.reset()

    report = await seed.run()
    assert report.organizations == 10
    assert report.requests_created == len(scenarios.SCENARIOS)


async def test_seed_refuses_outside_local_and_demo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    get_settings.cache_clear()
    try:
        assert get_settings().app_env == "prod"
        with pytest.raises(seed.DemoSeedNotAllowed):
            await seed.run()
        with pytest.raises(seed.DemoSeedNotAllowed):
            await seed.reset()
    finally:
        get_settings.cache_clear()


async def test_dual_organization_has_membership_per_side() -> None:
    await seed.run()

    issued = await login_demo("dual_manager")

    assert sorted(m.side for m in issued.memberships) == ["customer", "provider"]
    assert len(issued.organizations) == 1
    assert issued.organizations[0].kinds == ["customer", "provider"]


async def test_seed_publishes_provider_gallery() -> None:
    report = await seed.run()
    assert report.portfolio_images == 5

    profile = await get_public_profile(seed.ORG_PROVIDER)
    assert len(profile.gallery) == 3
    ext = await get_public_profile(seed.ORG_EXT1)
    assert len(ext.gallery) == 2

    viewer = UserActor(
        user_id=seed._id("user:outsider_manager"),
        membership_id=seed._id("membership:outsider:manager"),
        organization_id=seed.ORG_OUTSIDER,
        role="customer_manager",
    )
    content = await files.open_attachment(viewer, ids.decode("attachment", profile.gallery[0]))
    assert content.mime_type == "image/jpeg"

    again = await seed.run()
    assert again.portfolio_images == 0
    assert len((await get_public_profile(seed.ORG_PROVIDER)).gallery) == 3


async def test_reset_removes_demo_gallery() -> None:
    await seed.run()
    await seed.reset()
    report = await seed.run()
    assert report.portfolio_images == 5
