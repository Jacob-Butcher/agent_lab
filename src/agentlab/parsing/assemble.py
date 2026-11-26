import asyncio
import logging
from dataclasses import dataclass
from time import monotonic

from agentlab.config import Settings
from agentlab.parsing.base import ParsedDocument, ParseError, clean_text
from agentlab.parsing.images import ImageOcr, image_digest, prepare_image

logger = logging.getLogger(__name__)

MAX_IMAGES_PER_DOC = 50
MAX_ASSET_BYTES = 64 * 1024 * 1024
OCR_BUDGET_SECONDS = 120.0


@dataclass(frozen=True)
class Asset:
    name: str
    data: bytes


@dataclass(frozen=True)
class Assembled:
    markdown: str
    assets: list[Asset]


async def assemble(
    document: ParsedDocument, ocr: ImageOcr | None, settings: Settings
) -> Assembled:
    parts: list[str] = []
    assets: list[Asset] = []
    # 图片在全文档内去重：相同图片的 OCR 文字只在首次出现的位置插入。
    seen: set[str] = set()
    index = 0
    asset_bytes = 0
    ocr_deadline = monotonic() + OCR_BUDGET_SECONDS
    cap_logged = False
    bytes_logged = False
    for block in document.blocks:
        if block.kind == "page":
            if block.text:
                parts.append(f"## {block.text}")
        elif block.kind in ("text", "table"):
            text = clean_text(block.text)
            if text:
                parts.append(text)
        elif block.kind == "image":
            raw = block.image or b""
            raw_digest = image_digest(raw)
            if raw_digest in seen:
                continue
            seen.add(raw_digest)
            prepared = await asyncio.to_thread(prepare_image, raw)
            if prepared is None:
                continue
            data, ext = prepared
            digest = image_digest(data)
            if digest in seen:
                continue
            seen.add(digest)
            if len(assets) >= MAX_IMAGES_PER_DOC:
                if not cap_logged:
                    logger.warning(
                        "image limit %s reached, skipping remaining images",
                        MAX_IMAGES_PER_DOC,
                    )
                    cap_logged = True
                continue
            if asset_bytes + len(data) > MAX_ASSET_BYTES:
                if not bytes_logged:
                    logger.warning(
                        "asset byte budget %s exceeded, skipping remaining images",
                        MAX_ASSET_BYTES,
                    )
                    bytes_logged = True
                continue
            index += 1
            asset_bytes += len(data)
            assets.append(Asset(name=f"image-{index:02d}.{ext}", data=data))
            if ocr is not None:
                remaining = ocr_deadline - monotonic()
                if remaining <= 0:
                    logger.warning("OCR budget exhausted, skipping remaining OCR")
                    continue
                try:
                    text = clean_text(
                        await asyncio.wait_for(ocr.extract(data), timeout=remaining)
                    )
                except Exception:
                    logger.warning("image OCR failed", exc_info=True)
                    text = ""
                if text:
                    quoted = text.replace("\n", "\n> ")
                    parts.append(f"> 图片文字：{quoted}")
    markdown = clean_text("\n\n".join(parts))
    if len(markdown) > settings.max_doc_chars:
        raise ParseError(f"文档内容超过 {settings.max_doc_chars} 字符限制", 413)
    if not markdown:
        raise ParseError(
            "未提取到可入库内容（若文档只有图片，请确认 IMAGE_OCR_ENABLED 已开启）"
        )
    return Assembled(markdown=markdown, assets=assets)
