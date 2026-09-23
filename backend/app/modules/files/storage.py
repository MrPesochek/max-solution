from app.infra.config import get_settings
from app.infra.storage.base import FileStorage
from app.infra.storage.local import LocalFileStorage

_override: FileStorage | None = None
_cached: tuple[str, FileStorage] | None = None


def get_storage() -> FileStorage:
    global _cached
    if _override is not None:
        return _override
    settings = get_settings()
    if settings.file_storage_driver != "local":
        raise RuntimeError("драйвер хранилища пока только local")
    if _cached is None or _cached[0] != settings.file_storage_path:
        _cached = (settings.file_storage_path, LocalFileStorage(settings.file_storage_path))
    return _cached[1]


def set_storage(storage: FileStorage | None) -> None:
    global _override
    _override = storage
