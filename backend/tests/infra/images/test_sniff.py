import io

from PIL import Image

from app.infra.images.sniff import ImageFormat, sniff_image_format


def _encode(fmt: str, size=(4, 4)) -> bytes:
    img = Image.new("RGB", size, color=(10, 20, 30))
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def test_detects_jpeg() -> None:
    assert sniff_image_format(_encode("JPEG")) == ImageFormat.JPEG


def test_detects_png() -> None:
    assert sniff_image_format(_encode("PNG")) == ImageFormat.PNG


def test_detects_webp() -> None:
    assert sniff_image_format(_encode("WEBP")) == ImageFormat.WEBP


def test_rejects_html_disguised_as_jpeg() -> None:
    html = b"<html><body><script>alert(1)</script></body></html>"
    assert sniff_image_format(html) is None


def test_rejects_svg() -> None:
    svg = b"<?xml version='1.0'?><svg xmlns='http://www.w3.org/2000/svg'></svg>"
    assert sniff_image_format(svg) is None


def test_png_renamed_to_jpg_is_still_detected_as_png() -> None:
    data = _encode("PNG")
    assert sniff_image_format(data) == ImageFormat.PNG


def test_empty_and_short_input() -> None:
    assert sniff_image_format(b"") is None
    assert sniff_image_format(b"\xff\xd8") is None
