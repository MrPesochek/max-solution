import hashlib
import io

import pytest
from PIL import Image
from PIL.TiffImagePlugin import IFDRational

from app.infra.images.processor import ImageRejected, process_image
from app.infra.images.sniff import ImageFormat


def _jpeg_with_gps(size=(40, 20)) -> bytes:
    img = Image.new("RGB", size, (200, 50, 50))
    exif = img.getexif()
    exif[0x0112] = 3
    gps_ifd = exif.get_ifd(0x8825)
    gps_ifd[1] = "N"
    gps_ifd[2] = (IFDRational(40, 1), IFDRational(26, 1), IFDRational(0, 1))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def _png(size=(30, 30)) -> bytes:
    img = Image.new("RGBA", size, (10, 20, 30, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _animated_webp() -> bytes:
    frame1 = Image.new("RGB", (10, 10), (255, 0, 0))
    frame2 = Image.new("RGB", (10, 10), (0, 255, 0))
    buf = io.BytesIO()
    frame1.save(buf, format="WEBP", save_all=True, append_images=[frame2], duration=100, loop=0)
    return buf.getvalue()


def test_jpeg_exif_gps_stripped_and_orientation_applied() -> None:
    data = _jpeg_with_gps(size=(40, 20))
    result = process_image(data, max_pixels=1_000_000, max_bytes=1_000_000)

    assert result.format == ImageFormat.JPEG
    assert result.sha256_original == hashlib.sha256(data).hexdigest()

    safe_img = Image.open(io.BytesIO(result.data))
    exif = safe_img.getexif()
    assert 0x8825 not in exif
    assert len(exif) == 0

    thumb_img = Image.open(io.BytesIO(result.thumbnail))
    assert max(thumb_img.size) <= 512


def test_png_with_extension_renamed_to_jpg_is_processed_as_png() -> None:
    data = _png()
    result = process_image(data, max_pixels=1_000_000, max_bytes=1_000_000)
    assert result.format == ImageFormat.PNG


def test_html_disguised_as_jpeg_is_rejected() -> None:
    html = b"<html><body>not an image</body></html>"
    with pytest.raises(ImageRejected) as exc_info:
        process_image(html, max_pixels=1_000_000, max_bytes=1_000_000)
    assert exc_info.value.code == "unsupported_type"


def test_too_large_by_byte_size() -> None:
    data = _png()
    with pytest.raises(ImageRejected) as exc_info:
        process_image(data, max_pixels=1_000_000, max_bytes=len(data) - 1)
    assert exc_info.value.code == "too_large"


def test_too_many_pixels() -> None:
    data = _png(size=(100, 100))
    with pytest.raises(ImageRejected) as exc_info:
        process_image(data, max_pixels=100, max_bytes=10_000_000)
    assert exc_info.value.code == "too_many_pixels"


def test_corrupted_file_fails_decode() -> None:
    data = _png()
    corrupted = data[:-20]
    with pytest.raises(ImageRejected) as exc_info:
        process_image(corrupted, max_pixels=1_000_000, max_bytes=10_000_000)
    assert exc_info.value.code == "decode_failed"


def test_animated_webp_is_rejected() -> None:
    data = _animated_webp()
    with pytest.raises(ImageRejected) as exc_info:
        process_image(data, max_pixels=1_000_000, max_bytes=10_000_000)
    assert exc_info.value.code == "unsupported_type"


def test_thumbnail_preserves_aspect_ratio() -> None:
    data = _png(size=(1000, 500))
    result = process_image(data, max_pixels=10_000_000, max_bytes=10_000_000)
    thumb = Image.open(io.BytesIO(result.thumbnail))
    assert thumb.width == 512
    assert thumb.height == 256
