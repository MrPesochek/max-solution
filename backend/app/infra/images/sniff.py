from __future__ import annotations

from enum import StrEnum


class ImageFormat(StrEnum):
    JPEG = "jpeg"
    PNG = "png"
    WEBP = "webp"


_JPEG_SIGNATURE = b"\xff\xd8\xff"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def sniff_image_format(data: bytes) -> ImageFormat | None:
    if data.startswith(_JPEG_SIGNATURE):
        return ImageFormat.JPEG
    if data.startswith(_PNG_SIGNATURE):
        return ImageFormat.PNG
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ImageFormat.WEBP
    return None
