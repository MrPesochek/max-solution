import pytest
from sqlalchemy import select

from app.adapters.operator import cli
from app.core import ids
from app.core.errors import NotFound
from app.db import session as db_session
from app.db.models import AuditEntry, PlatformRole, ProviderProfile, User
from tests.support import make_provider

pytestmark = pytest.mark.usefixtures("clean_db")


async def test_grant_and_revoke_operator_role() -> None:
    parser = cli.build_parser()
    await cli.run(parser.parse_args(["grant-operator", "--max-user-id", "cli-op"]))

    async with db_session.transaction() as s:
        user = (await s.execute(select(User).where(User.max_user_id == "cli-op"))).scalar_one()
        roles = list(
            (await s.execute(select(PlatformRole).where(PlatformRole.user_id == user.id))).scalars()
        )
    assert [row.role for row in roles] == ["operator"]
    assert roles[0].revoked_at is None

    await cli.run(parser.parse_args(["revoke-operator", "--max-user-id", "cli-op"]))
    async with db_session.transaction() as s:
        roles = list((await s.execute(select(PlatformRole))).scalars())
        audit = {row.action for row in (await s.execute(select(AuditEntry))).scalars()}
    assert roles[0].revoked_at is not None
    assert {"platform_role.grant", "platform_role.revoke"} <= audit


async def test_suspend_and_reinstate_provider_from_cli() -> None:
    provider = await make_provider("cli-prov", status="active", accepting=True, verified=True)
    organization_id = ids.encode("organization", provider.organization_id)
    parser = cli.build_parser()

    await cli.run(
        parser.parse_args(
            [
                "suspend-provider",
                "--organization-id",
                organization_id,
                "--reason",
                "жалоба на качество",
            ]
        )
    )
    assert await _status(provider.organization_id) == "suspended"

    await cli.run(
        parser.parse_args(
            [
                "reinstate-provider",
                "--organization-id",
                organization_id,
                "--reason",
                "жалоба не подтвердилась",
            ]
        )
    )
    assert await _status(provider.organization_id) == "active"

    async with db_session.transaction() as s:
        entries = [
            row
            for row in (await s.execute(select(AuditEntry))).scalars()
            if row.action.startswith("provider_profile.")
        ]
    assert {row.action for row in entries} == {
        "provider_profile.suspend",
        "provider_profile.reinstate",
    }
    assert all(row.details.get("reason") for row in entries)
    assert all(row.actor_kind == "system" for row in entries)


async def test_cli_rejects_unknown_organization() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "suspend-provider",
            "--organization-id",
            "org_000000000000000000000A",
            "--reason",
            "нет такого",
        ]
    )
    with pytest.raises(NotFound):
        await cli.run(args)


async def _status(organization_id: object) -> str:
    async with db_session.transaction() as s:
        profile = (
            await s.execute(
                select(ProviderProfile).where(ProviderProfile.organization_id == organization_id)
            )
        ).scalar_one()
        return profile.status
