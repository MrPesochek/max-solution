from pathlib import Path

import pytest

from app.infra.storage.base import make_storage_key
from app.infra.storage.local import LocalFileStorage, StorageKeyError


@pytest.fixture
def storage(tmp_path: Path) -> LocalFileStorage:
    return LocalFileStorage(tmp_path / "files")


async def test_put_and_open_roundtrip_bytes(storage: LocalFileStorage) -> None:
    key = make_storage_key("attachments")
    size = await storage.put(key, b"hello world")
    assert size == 11
    assert await storage.exists(key)

    chunks = [chunk async for chunk in storage.open(key)]
    assert b"".join(chunks) == b"hello world"


async def test_put_streaming_source(storage: LocalFileStorage) -> None:
    async def gen():
        yield b"part1-"
        yield b"part2"

    key = make_storage_key("attachments")
    size = await storage.put(key, gen())
    assert size == len(b"part1-part2")
    data = b"".join([chunk async for chunk in storage.open(key)])
    assert data == b"part1-part2"


async def test_delete_is_idempotent(storage: LocalFileStorage) -> None:
    key = make_storage_key("attachments")
    await storage.put(key, b"x")
    await storage.delete(key)
    assert not await storage.exists(key)
    await storage.delete(key)


async def test_open_missing_file_raises(storage: LocalFileStorage) -> None:
    with pytest.raises(FileNotFoundError):
        async for _ in storage.open("attachments/2026/01/01/does-not-exist"):
            pass


async def test_write_is_atomic_no_partial_file_visible(
    storage: LocalFileStorage, tmp_path: Path
) -> None:
    key = "attachments/2026/01/01/abc.bin"
    await storage.put(key, b"data")
    leftovers = list((tmp_path / "files").rglob(".*"))
    assert leftovers == []


@pytest.mark.parametrize(
    "bad_key",
    [
        "../escape",
        "/etc/passwd",
        "a/../../b",
        "",
    ],
)
async def test_rejects_keys_escaping_root(storage: LocalFileStorage, bad_key: str) -> None:
    with pytest.raises(StorageKeyError):
        await storage.put(bad_key, b"x")


async def test_make_storage_key_is_unpredictable_and_dated() -> None:
    key1 = make_storage_key("photos")
    key2 = make_storage_key("photos")
    assert key1 != key2
    assert key1.startswith("photos/")
    assert key1.count("/") == 4


async def test_iter_keys_lists_files_under_prefix(storage: LocalFileStorage) -> None:
    key1 = make_storage_key("attachments")
    key2 = make_storage_key("attachments")
    other = make_storage_key("portfolio")
    for key in (key1, key2, other):
        await storage.put(key, b"x")

    under_prefix = {key async for key in storage.iter_keys("attachments")}
    assert under_prefix == {key1, key2}

    everything = {key async for key in storage.iter_keys("")}
    assert everything == {key1, key2, other}


async def test_iter_keys_on_missing_prefix_yields_nothing(storage: LocalFileStorage) -> None:
    assert [key async for key in storage.iter_keys("nothing-here")] == []


async def test_iter_keys_ignores_temp_files_of_ongoing_upload(
    storage: LocalFileStorage, tmp_path: Path
) -> None:
    key = make_storage_key("attachments")
    await storage.put(key, b"data")
    leftover = (tmp_path / "files" / key).with_name(f".{Path(key).name}.leftover.tmp")
    leftover.write_bytes(b"partial")

    assert [key_ async for key_ in storage.iter_keys("")] == [key]


async def test_iter_keys_rejects_prefix_escaping_root(storage: LocalFileStorage) -> None:
    with pytest.raises(StorageKeyError):
        async for _ in storage.iter_keys("../escape"):
            pass
