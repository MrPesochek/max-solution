from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterable, AsyncIterator
from pathlib import Path, PurePosixPath


class StorageKeyError(ValueError):
    pass


class LocalFileStorage:
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._root_resolved = self._root.resolve()

    def _resolve(self, key: str) -> Path:
        if not key:
            raise StorageKeyError("пустой ключ")
        normalized = PurePosixPath(key)
        if (
            normalized.is_absolute()
            or ".." in normalized.parts
            or str(normalized) != key.rstrip("/")
        ):
            raise StorageKeyError(f"недопустимый ключ хранилища: {key!r}")
        return self._within_root(self._root / key, key)

    def _resolve_dir(self, prefix: str) -> Path:
        """Как `_resolve`, но для каталога-префикса: пустая строка — корень хранилища."""
        if prefix == "":
            return self._root_resolved
        normalized = PurePosixPath(prefix)
        if normalized.is_absolute() or ".." in normalized.parts:
            raise StorageKeyError(f"недопустимый префикс: {prefix!r}")
        return self._within_root(self._root / prefix, prefix)

    def _within_root(self, candidate: Path, original: str) -> Path:
        resolved = candidate.resolve()
        if resolved != self._root_resolved and self._root_resolved not in resolved.parents:
            raise StorageKeyError(f"путь выходит за пределы хранилища: {original!r}")
        return resolved

    async def put(self, key: str, data: bytes | AsyncIterable[bytes]) -> int:
        path = self._resolve(key)
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        size = 0
        try:
            if isinstance(data, bytes | bytearray):
                payload = bytes(data)
                await asyncio.to_thread(tmp_path.write_bytes, payload)
                size = len(payload)
            else:
                handle = await asyncio.to_thread(tmp_path.open, "wb")
                try:
                    async for chunk in data:
                        await asyncio.to_thread(handle.write, chunk)
                        size += len(chunk)
                finally:
                    await asyncio.to_thread(handle.close)
            await asyncio.to_thread(os.replace, tmp_path, path)
        except BaseException:
            await asyncio.to_thread(tmp_path.unlink, missing_ok=True)
            raise
        return size

    async def open(self, key: str) -> AsyncIterator[bytes]:
        path = self._resolve(key)
        if not await asyncio.to_thread(path.is_file):
            raise FileNotFoundError(key)
        handle = await asyncio.to_thread(path.open, "rb")
        try:
            while True:
                chunk = await asyncio.to_thread(handle.read, 65536)
                if not chunk:
                    break
                yield chunk
        finally:
            await asyncio.to_thread(handle.close)

    async def delete(self, key: str) -> None:
        path = self._resolve(key)
        await asyncio.to_thread(path.unlink, missing_ok=True)

    async def exists(self, key: str) -> bool:
        path = self._resolve(key)
        return await asyncio.to_thread(path.is_file)

    async def iter_keys(self, prefix: str) -> AsyncIterator[str]:
        """Файлы, чьё имя не начинается с точки: временные файлы `put()` пишутся
        именно так и не должны попасть под уборку осиротевших ключей."""
        base = self._resolve_dir(prefix)
        if not await asyncio.to_thread(base.is_dir):
            return
        paths = await asyncio.to_thread(
            lambda: sorted(p for p in base.rglob("*") if p.is_file() and not p.name.startswith("."))
        )
        for path in paths:
            yield path.relative_to(self._root_resolved).as_posix()
