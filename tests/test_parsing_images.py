import io

from PIL import Image

from agentlab.config import Settings
from agentlab.parsing.images import build_ocr, image_digest, prepare_image
from tests.docgen import png_bytes


def _settings(**kwargs):
    return Settings(_env_file=None, **kwargs)


def test_prepare_image_filters_small_images():
    assert prepare_image(png_bytes(50, 50)) is None


def test_prepare_image_normalizes_to_png():
    prepared = prepare_image(png_bytes(200, 100, (10, 20, 30)))
    assert prepared is not None
    data, ext = prepared
    assert ext == "png"
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(io.BytesIO(data)) as image:
        assert image.size == (200, 100)
        assert image.format == "PNG"


def test_prepare_image_downscales_and_uses_jpeg_for_photos():
    buffer = io.BytesIO()
    Image.new("RGB", (3000, 1500), (1, 2, 3)).save(buffer, format="JPEG")
    prepared = prepare_image(buffer.getvalue())
    assert prepared is not None
    data, ext = prepared
    assert ext == "jpg"
    with Image.open(io.BytesIO(data)) as image:
        assert max(image.size) <= 2048


def test_prepare_image_rejects_corrupt_small_and_huge():
    assert prepare_image(b"not an image") is None
    assert prepare_image(b"") is None
    assert prepare_image(png_bytes(50, 50)) is None
    buffer = io.BytesIO()
    Image.new("1", (6000, 6000)).save(buffer, format="PNG")
    assert prepare_image(buffer.getvalue()) is None


def test_prepare_image_flattens_transparency_to_white():
    image = Image.new("RGBA", (200, 100), (0, 0, 0, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    prepared = prepare_image(buffer.getvalue())
    assert prepared is not None
    data, _ = prepared
    with Image.open(io.BytesIO(data)) as converted:
        assert converted.getpixel((0, 0)) == (255, 255, 255)


def test_image_digest_distinguishes_payloads():
    first = png_bytes(200, 100, (1, 2, 3))
    second = png_bytes(200, 100, (4, 5, 6))
    assert image_digest(first) == image_digest(first)
    assert image_digest(first) != image_digest(second)


def test_build_ocr_disabled_or_without_key():
    assert build_ocr(_settings(image_ocr_enabled=False, dashscope_api_key="x")) is None
    assert build_ocr(_settings(image_ocr_enabled=True, dashscope_api_key="")) is None


def test_build_ocr_positive_and_mock_disabled():
    assert (
        build_ocr(
            _settings(image_ocr_enabled=True, dashscope_api_key="key")
        )
        is not None
    )
    assert (
        build_ocr(
            _settings(
                image_ocr_enabled=True,
                dashscope_api_key="key",
                model_provider="mock",
            )
        )
        is None
    )
