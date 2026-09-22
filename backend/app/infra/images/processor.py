from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

from PIL import Image, ImageOps

from app.infra.images.sniff import ImageFormat, sniff_image_format

THUMBNAIL_MAX_SIDE = 512

_PIL_FORMAT: dict[ImageFormat, str] = {
    ImageFormat.JPEG: "JPEG",
    ImageFormat.PNG: "PNG",
    ImageFormat.WEBP: "WEBP",
}


class ImageRejected(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ProcessedImage:
    data: bytes
    thumbnail: bytes
    width: int
    height: int
    format: ImageFormat
    sha256_original: str


def _open_for_inspection(data: bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as exc:
        raise ImageRejected("decode_failed") from exc
    return img


def _strip_metadata_and_reencode(img: Image.Image, fmt: ImageFormat) -> Image.Image:
    oriented = ImageOps.exif_transpose(img)
    if oriented is None:
        oriented = img
    if fmt is ImageFormat.JPEG and oriented.mode in ("RGBA", "P", "LA"):
        oriented = oriented.convert("RGB")
    elif fmt is not ImageFormat.JPEG and oriented.mode == "P":
        oriented = oriented.convert("RGBA")
    clean = Image.new(oriented.mode, oriented.size)
    clean.paste(oriented, (0, 0))
    return clean


def _encode(img: Image.Image, fmt: ImageFormat) -> bytes:
    buf = io.BytesIO()
    save_kwargs: dict[str, object] = {}
    if fmt is ImageFormat.JPEG:
        save_kwargs["quality"] = 90
    img.save(buf, format=_PIL_FORMAT[fmt], **save_kwargs)
    return buf.getvalue()


def process_image(data: bytes, *, max_pixels: int, max_bytes: int) -> ProcessedImage:
    if len(data) > max_bytes:
        raise ImageRejected("too_large")

    fmt = sniff_image_format(data)
    if fmt is None:
        raise ImageRejected("unsupported_type")

    sha256_original = hashlib.sha256(data).hexdigest()

    original_limit = Image.MAX_IMAGE_PIXELS
    try:
        Image.MAX_IMAGE_PIXELS = None
        try:
            probe = Image.open(io.BytesIO(data))
            declared_format = (probe.format or "").upper()
            width, height = probe.size
            n_frames = getattr(probe, "n_frames", 1)
        except Exception as exc:
            raise ImageRejected("decode_failed") from exc

        if declared_format != _PIL_FORMAT[fmt]:
            raise ImageRejected("unsupported_type")
        if width <= 0 or height <= 0:
            raise ImageRejected("decode_failed")
        if width * height > max_pixels:
            raise ImageRejected("too_many_pixels")
        if n_frames and n_frames > 1:
            raise ImageRejected("unsupported_type")

        try:
            verifier = Image.open(io.BytesIO(data))
            verifier.verify()
        except Exception as exc:
            raise ImageRejected("decode_failed") from exc

        img = _open_for_inspection(data)
        try:
            safe_img = _strip_metadata_and_reencode(img, fmt)
        except ImageRejected:
            raise
        except Exception as exc:
            raise ImageRejected("decode_failed") from exc

        safe_bytes = _encode(safe_img, fmt)

        thumb_img = safe_img.copy()
        thumb_img.thumbnail((THUMBNAIL_MAX_SIDE, THUMBNAIL_MAX_SIDE), Image.Resampling.LANCZOS)
        thumb_bytes = _encode(thumb_img, fmt)

        return ProcessedImage(
            data=safe_bytes,
            thumbnail=thumb_bytes,
            width=safe_img.width,
            height=safe_img.height,
            format=fmt,
            sha256_original=sha256_original,
        )
    finally:
        Image.MAX_IMAGE_PIXELS = original_limit
