import time

from app.infra.images.processor import ProcessedImage
from app.infra.images.sniff import ImageFormat


def sleep_forever_worker(data: bytes, *, max_pixels: int, max_bytes: int) -> ProcessedImage:
    time.sleep(60)
    raise AssertionError("не должно быть достигнуто — процесс должен быть убит по таймауту")


def instant_worker(data: bytes, *, max_pixels: int, max_bytes: int) -> ProcessedImage:
    return ProcessedImage(
        data=data,
        thumbnail=data,
        width=1,
        height=1,
        format=ImageFormat.PNG,
        sha256_original="deadbeef",
    )
