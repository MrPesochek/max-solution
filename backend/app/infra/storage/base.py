from __future__ import annotations

import datetime
import uuid
from collections.abc import AsyncIterable, AsyncIterator
from typing import Protocol


class FileStorage(Protocol):
    async def put(self, key: str, data: bytes | AsyncIterable[bytes]) -> int:
        """Записывает файл атомарно, возвращает размер в байтах."""
        ...

    def open(self, key: str) -> AsyncIterator[bytes]:
        """Потоковое чтение файла. Поднимает FileNotFoundError, если ключа нет."""
        ...

    async def delete(self, key: str) -> None: ...

    async def exists(self, key: str) -> bool: ...

    def iter_keys(self, prefix: str) -> AsyncIterator[str]:
        """Обход ключей под префиксом (`""` — всё хранилище). Для уборки осиротевших файлов."""
        ...


def make_storage_key(prefix: str) -> str:
    """Ключ вида `<prefix>/<YYYY>/<MM>/<DD>/<uuid4>` — без пользовательских данных."""
    if not prefix:
        raise ValueError("prefix не должен быть пустым")
    today = datetime.datetime.now(tz=datetime.UTC)
    return f"{prefix}/{today:%Y/%m/%d}/{uuid.uuid4().hex}"
