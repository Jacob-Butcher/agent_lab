import base64
import io
import logging
from typing import Protocol

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from PIL import Image, ImageOps

from agentlab.config import Settings
from agentlab.parsing.base import sha256_bytes

logger = logging.getLogger(__name__)

MIN_DIMENSION = 100
MAX_DIMENSION = 2048
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 30_000_000
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
JPEG_QUALITY = 85
OCR_PROMPT = "请提取图片中的全部文字，保持原有换行与结构，不要解释。"


class ImageOcr(Protocol):
    async def extract(self, image: bytes) -> str: ...


def _flatten(image: Image.Image) -> Image.Image:
    if image.mode in {"RGBA", "LA"} or (
        image.mode == "P" and "transparency" in image.info
    ):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.split()[-1])
        return background
    return image.convert("RGB")


def prepare_image(data: bytes) -> tuple[bytes, str] | None:
    if not data or len(data) > MAX_IMAGE_BYTES:
        return None
    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            if width < MIN_DIMENSION or height < MIN_DIMENSION:
                return None
            if width * height > MAX_PIXELS:
                logger.warning("skip oversized image %sx%s", width, height)
                return None
            source_format = (image.format or "").upper()
            transposed = ImageOps.exif_transpose(image)
            transposed.load()
            converted = _flatten(transposed)
            if max(converted.size) > MAX_DIMENSION:
                converted.thumbnail((MAX_DIMENSION, MAX_DIMENSION))
            if source_format in {"JPEG", "JPG"}:
                out_format, ext = "JPEG", "jpg"
            else:
                out_format, ext = "PNG", "png"
            kwargs: dict[str, int | bool] = {"optimize": True}
            if out_format == "JPEG":
                kwargs["quality"] = JPEG_QUALITY
            buffer = io.BytesIO()
            converted.save(buffer, format=out_format, **kwargs)
            encoded = buffer.getvalue()
            if len(encoded) > MAX_OUTPUT_BYTES and out_format == "PNG":
                buffer = io.BytesIO()
                converted.save(
                    buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True
                )
                encoded, ext = buffer.getvalue(), "jpg"
            if len(encoded) > MAX_OUTPUT_BYTES:
                logger.warning("skip image after encoding: %s bytes", len(encoded))
                return None
            return encoded, ext
    except Exception:
        logger.warning("skip unsupported image", exc_info=True)
        return None


def image_digest(data: bytes) -> str:
    return sha256_bytes(data)


class DashScopeImageOcr:
    def __init__(self, settings: Settings) -> None:
        self.llm = ChatOpenAI(
            model=settings.ocr_model,
            api_key=settings.dashscope_api_key,
            base_url=settings.dashscope_base_url,
            timeout=30,
            max_retries=0,
            temperature=0,
            max_tokens=2048,
        )

    async def extract(self, image: bytes) -> str:
        mime = "jpeg" if image.startswith(b"\xff\xd8") else "png"
        data_url = f"data:image/{mime};base64," + base64.b64encode(image).decode("ascii")
        message = HumanMessage(
            content=[
                {"type": "text", "text": OCR_PROMPT},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]
        )
        try:
            result = await self.llm.ainvoke([message])
        except Exception:
            logger.warning("image OCR request failed", exc_info=True)
            return ""
        content = result.content
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            return "".join(
                str(part.get("text") or "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            ).strip()
        return ""


def build_ocr(settings: Settings) -> ImageOcr | None:
    if (
        not settings.image_ocr_enabled
        or settings.is_mock
        or not settings.dashscope_api_key
    ):
        return None
    return DashScopeImageOcr(settings)
