from collections.abc import AsyncIterator, Iterator
from typing import Annotated

import httpx
import pytest
from fastapi import FastAPI, File, UploadFile
from httpx import ASGITransport

from app.adapters.http.body_limit import BodyLimitMiddleware
from app.adapters.http.errors import install_error_handlers
from app.infra.config import Settings
from tests import factories

LIMIT = 64 * 1024
OVERHEAD = 1024


@pytest.fixture(autouse=True)
def settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    yield from factories.apply_test_settings(
        monkeypatch,
        MAX_UPLOAD_BYTES=str(LIMIT),
        UPLOAD_BODY_OVERHEAD_BYTES=str(OVERHEAD),
        MAX_REQUEST_BODY_BYTES="1024",
    )


def _app() -> tuple[FastAPI, list[int]]:
    app = FastAPI()
    seen: list[int] = []

    @app.post("/upload")
    async def upload(file: Annotated[UploadFile, File()]) -> dict[str, int]:
        data = await file.read()
        seen.append(len(data))
        return {"size": len(data)}

    @app.post("/json")
    async def echo(payload: dict[str, str]) -> dict[str, int]:
        return {"keys": len(payload)}

    install_error_handlers(app)
    app.add_middleware(BodyLimitMiddleware)
    return app, seen


def _multipart(size: int) -> tuple[bytes, str]:
    boundary = "limit-test-boundary"
    body = (
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="a.jpg"\r\n'
            "Content-Type: image/jpeg\r\n\r\n"
        ).encode()
        + b"x" * size
        + f"\r\n--{boundary}--\r\n".encode()
    )
    return body, f"multipart/form-data; boundary={boundary}"


async def _chunks(data: bytes, step: int = 4096) -> AsyncIterator[bytes]:
    for start in range(0, len(data), step):
        yield data[start : start + step]


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app), base_url="http://test")


async def test_chunked_upload_over_limit_is_cut_with_413() -> None:
    app, seen = _app()
    body, content_type = _multipart(LIMIT + 2 * OVERHEAD)
    async with _client(app) as client:
        response = await client.post(
            "/upload", content=_chunks(body), headers={"Content-Type": content_type}
        )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
    assert seen == []


async def test_declared_length_over_limit_is_refused_before_reading() -> None:
    app, seen = _app()
    body, content_type = _multipart(LIMIT + 2 * OVERHEAD)
    async with _client(app) as client:
        response = await client.post(
            "/upload", content=body, headers={"Content-Type": content_type}
        )
    assert response.status_code == 413
    assert seen == []


async def test_upload_within_limit_passes() -> None:
    app, seen = _app()
    body, content_type = _multipart(LIMIT)
    async with _client(app) as client:
        response = await client.post(
            "/upload", content=_chunks(body), headers={"Content-Type": content_type}
        )
    assert response.status_code == 200
    assert seen == [LIMIT]


async def test_json_has_its_own_smaller_limit() -> None:
    app, _ = _app()
    async with _client(app) as client:
        small = await client.post("/json", json={"a": "b"})
        large = await client.post("/json", json={"a": "b" * 4096})
    assert small.status_code == 200
    assert large.status_code == 413
