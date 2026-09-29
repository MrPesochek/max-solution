from collections.abc import Iterator

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WebhookSubscription
from app.infra import crypto_keys
from app.infra.config import Settings
from app.infra.crypto import SecretBox, SecretBoxError
from tests import factories

OLD_KEY = factories.SECRETS_ENCRYPTION_KEY
NEW_KEY = Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    yield from factories.integration_settings(monkeypatch)


async def _subscription(session: AsyncSession, secret: str = "s3cret") -> WebhookSubscription:
    org = await factories.create_organization(session, customer=False, provider=True)
    client, _ = await factories.create_integration_client(session, org)
    subscription = await factories.create_webhook_subscription(session, client, secret=secret)
    await session.commit()
    return subscription


@pytest.fixture(autouse=True)
def _keep_test_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop() -> None:
        return None

    monkeypatch.setattr(crypto_keys.db_session, "dispose", _noop)


def _use_key(monkeypatch: pytest.MonkeyPatch, key: str) -> None:
    monkeypatch.setenv("SECRETS_ENCRYPTION_KEY", key)
    crypto_keys.get_settings.cache_clear()


def test_fingerprint_is_stable_and_not_the_key() -> None:
    assert crypto_keys.key_fingerprint(OLD_KEY) == crypto_keys.key_fingerprint(f" {OLD_KEY} ")
    assert crypto_keys.key_fingerprint(OLD_KEY) not in OLD_KEY
    assert crypto_keys.key_fingerprint(OLD_KEY) != crypto_keys.key_fingerprint(NEW_KEY)


@pytest.mark.asyncio
async def test_startup_passes_without_subscriptions_and_without_key(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_key(monkeypatch, "")
    await crypto_keys.verify_on_startup()


@pytest.mark.asyncio
async def test_startup_passes_with_matching_key(db_session: AsyncSession) -> None:
    await _subscription(db_session)
    await crypto_keys.verify_on_startup()


@pytest.mark.asyncio
async def test_startup_fails_on_foreign_key(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Восстановление дампа без ключа: api не стартует молча с новым ключом."""
    await _subscription(db_session)
    _use_key(monkeypatch, NEW_KEY)
    with pytest.raises(crypto_keys.KeyMismatchError, match="SECRETS_ENCRYPTION_KEY"):
        await crypto_keys.verify_on_startup()


@pytest.mark.asyncio
async def test_startup_fails_on_missing_key(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _subscription(db_session)
    _use_key(monkeypatch, "")
    with pytest.raises(crypto_keys.KeyMismatchError):
        await crypto_keys.verify_on_startup()


@pytest.mark.asyncio
async def test_rotation_reencrypts_with_first_key(db_session: AsyncSession) -> None:
    await _subscription(db_session, secret="first")
    both = f"{NEW_KEY},{OLD_KEY}"

    before = await crypto_keys.check_stored_secrets(db_session, both)
    assert before == crypto_keys.KeyCheck(total=1, unreadable=0, stale=1)

    assert await crypto_keys.rotate_stored_secrets(db_session, both) == 1
    await db_session.commit()

    token = (await db_session.execute(select(WebhookSubscription.secret_encrypted))).scalar_one()
    assert SecretBox(NEW_KEY).decrypt(token) == b"first"
    with pytest.raises(SecretBoxError):
        SecretBox(OLD_KEY).decrypt(token)
    after = await crypto_keys.check_stored_secrets(db_session, both)
    assert after == crypto_keys.KeyCheck(total=1, unreadable=0, stale=0)


@pytest.mark.asyncio
async def test_rotation_aborts_on_unreadable_secret(db_session: AsyncSession) -> None:
    subscription_id = (await _subscription(db_session)).id
    third = Fernet.generate_key().decode()
    with pytest.raises(SecretBoxError):
        await crypto_keys.rotate_stored_secrets(db_session, f"{NEW_KEY},{third}")
    await db_session.rollback()
    token = (
        await db_session.execute(
            select(WebhookSubscription.secret_encrypted).where(
                WebhookSubscription.id == subscription_id
            )
        )
    ).scalar_one()
    assert SecretBox(OLD_KEY).decrypt(token) == b"s3cret"


@pytest.mark.asyncio
async def test_check_reports_unreadable(db_session: AsyncSession) -> None:
    await _subscription(db_session)
    result = await crypto_keys.check_stored_secrets(db_session, NEW_KEY)
    assert result == crypto_keys.KeyCheck(total=1, unreadable=1, stale=0)


def test_cli_generate_prints_valid_key(capsys: pytest.CaptureFixture[str]) -> None:
    assert crypto_keys.main(["generate"]) == 0
    key = capsys.readouterr().out.strip()
    SecretBox(key)


def test_cli_fingerprint_marks_primary_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use_key(monkeypatch, f"{NEW_KEY},{OLD_KEY}")
    assert crypto_keys.main(["fingerprint"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0].startswith(crypto_keys.key_fingerprint(NEW_KEY))
    assert "шифрует" in lines[0]
    assert "только расшифровывает" in lines[1]
    assert NEW_KEY not in "\n".join(lines)


def test_cli_rejects_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_key(monkeypatch, "")
    assert crypto_keys.main(["fingerprint"]) == 2
