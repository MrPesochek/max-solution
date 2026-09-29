from maxapi.types.updates import UpdateUnionAdapter

from app.adapters.bot.updates import update_key
from tests.bot.conftest import bot_started, message_callback, message_created


def _key(raw: dict[str, object]) -> str:
    return update_key(UpdateUnionAdapter.validate_python(raw))


def test_message_key_is_message_id() -> None:
    event = message_created("привет", mid="mid-42")
    assert _key(event) == "message_created:mid-42"
    assert _key(event) == _key(dict(event))


def test_callback_key_is_callback_id() -> None:
    event = message_callback("m:organization", callback_id="cb-9")
    assert _key(event) == "message_callback:cb-9"


def test_different_presses_get_different_keys() -> None:
    first = message_callback("m:organization", callback_id="cb-1")
    second = message_callback("m:organization", callback_id="cb-2")
    assert _key(first) != _key(second)


def test_event_without_own_id_uses_chat_user_and_time() -> None:
    event = bot_started()
    assert _key(event) == f"bot_started:500:77:{event['timestamp']}"
