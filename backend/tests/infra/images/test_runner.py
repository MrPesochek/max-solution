import time

import pytest

from app.infra.images.processor import ImageRejected, process_image
from app.infra.images.runner import process_image_isolated
from tests.infra.images._slow_worker import instant_worker, sleep_forever_worker


async def test_success_path_matches_direct_processing(png_bytes: bytes) -> None:
    direct = process_image(png_bytes, max_pixels=1_000_000, max_bytes=1_000_000)
    isolated = await process_image_isolated(png_bytes, max_pixels=1_000_000, max_bytes=1_000_000)
    assert isolated.format == direct.format
    assert isolated.width == direct.width
    assert isolated.height == direct.height
    assert isolated.sha256_original == direct.sha256_original


async def test_rejection_propagates_through_isolation(png_bytes: bytes) -> None:
    with pytest.raises(ImageRejected) as exc_info:
        await process_image_isolated(png_bytes, max_pixels=1_000_000, max_bytes=len(png_bytes) - 1)
    assert exc_info.value.code == "too_large"


async def test_timeout_kills_process_and_raises_timeout_code() -> None:
    started = time.monotonic()
    with pytest.raises(ImageRejected) as exc_info:
        await process_image_isolated(
            b"irrelevant",
            max_pixels=1_000_000,
            max_bytes=1_000_000,
            timeout=0.3,
            worker=sleep_forever_worker,
        )
    elapsed = time.monotonic() - started
    assert exc_info.value.code == "timeout"
    assert elapsed < 5.0


async def test_custom_worker_result_is_returned() -> None:
    result = await process_image_isolated(
        b"x", max_pixels=1_000_000, max_bytes=1_000_000, worker=instant_worker
    )
    assert result.sha256_original == "deadbeef"


@pytest.fixture
def png_bytes() -> bytes:
    import io

    from PIL import Image

    img = Image.new("RGB", (20, 20), (1, 2, 3))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
