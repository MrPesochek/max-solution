from __future__ import annotations

import asyncio
import contextlib
import multiprocessing as mp
import platform
from multiprocessing.connection import Connection
from typing import Any, Protocol

from app.infra.images.processor import ImageRejected, ProcessedImage, process_image

try:
    import resource
except ImportError:
    resource = None  # type: ignore[assignment]

DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MEMORY_LIMIT_BYTES = 512 * 1024 * 1024


class Worker(Protocol):
    def __call__(self, data: bytes, *, max_pixels: int, max_bytes: int) -> ProcessedImage: ...


def _apply_memory_limit(memory_limit_bytes: int) -> None:
    if resource is None or platform.system() != "Linux":
        return
    with contextlib.suppress(Exception):
        resource.setrlimit(resource.RLIMIT_AS, (memory_limit_bytes, memory_limit_bytes))


def _worker_entry(
    conn: Connection,
    worker: Worker,
    data: bytes,
    max_pixels: int,
    max_bytes: int,
    memory_limit_bytes: int,
) -> None:
    _apply_memory_limit(memory_limit_bytes)
    try:
        result = worker(data, max_pixels=max_pixels, max_bytes=max_bytes)
        conn.send(("ok", result))
    except ImageRejected as exc:
        conn.send(("rejected", exc.code))
    except Exception as exc:
        conn.send(("error", str(exc)))
    finally:
        conn.close()


async def process_image_isolated(
    data: bytes,
    *,
    max_pixels: int,
    max_bytes: int,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,  # noqa: ASYNC109 — часть требуемого контракта функции
    memory_limit_bytes: int = DEFAULT_MEMORY_LIMIT_BYTES,
    worker: Worker = process_image,
) -> ProcessedImage:
    ctx = mp.get_context("spawn")
    parent_conn, child_conn = ctx.Pipe(duplex=False)
    process = ctx.Process(
        target=_worker_entry,
        args=(child_conn, worker, data, max_pixels, max_bytes, memory_limit_bytes),
        daemon=True,
    )
    process.start()
    child_conn.close()

    loop = asyncio.get_running_loop()
    result: tuple[str, Any] | None = None
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(None, parent_conn.recv), timeout=timeout
        )
    except TimeoutError:
        process.kill()
        await loop.run_in_executor(None, process.join)
        raise ImageRejected("timeout") from None
    except EOFError:
        pass
    finally:
        parent_conn.close()

    await loop.run_in_executor(None, process.join)

    if result is None:
        raise ImageRejected("decode_failed")

    status, payload = result
    if status == "ok":
        return payload  # type: ignore[no-any-return]
    if status == "rejected":
        raise ImageRejected(str(payload))
    raise ImageRejected("decode_failed")
