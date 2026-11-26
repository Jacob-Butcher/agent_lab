import io
import logging
from pathlib import Path

from pptx import Presentation

from agentlab.config import Settings
from agentlab.parsing.base import (
    Block,
    ParsedDocument,
    ParseError,
    clean_text,
    table_to_markdown,
)

logger = logging.getLogger(__name__)


def parse_pptx(filename: str, data: bytes, settings: Settings) -> ParsedDocument:
    try:
        presentation = Presentation(io.BytesIO(data))
        slides = list(presentation.slides)
        if len(slides) > settings.max_doc_pages:
            raise ParseError(f"幻灯片数量超过 {settings.max_doc_pages} 页限制", 413)
        blocks: list[Block] = []
        for number, slide in enumerate(slides, 1):
            slide_blocks: list[Block] = []
            # Top-level shapes only; grouped shapes (GROUP) are a known P1 limitation.
            for shape in slide.shapes:
                if shape.has_text_frame:
                    text = clean_text(
                        "\n".join(
                            paragraph.text
                            for paragraph in shape.text_frame.paragraphs
                            if paragraph.text.strip()
                        )
                    )
                    if text:
                        slide_blocks.append(Block("text", text=text))
                elif shape.has_table:
                    markdown = table_to_markdown(
                        [[cell.text for cell in row.cells] for row in shape.table.rows]
                    )
                    if markdown:
                        slide_blocks.append(Block("table", text=markdown))
                else:
                    try:
                        image = shape.image
                    except AttributeError:
                        image = None
                    except Exception:
                        logger.warning("image extraction failed", exc_info=True)
                        image = None
                    if image is not None:
                        slide_blocks.append(
                            Block("image", image=image.blob, image_ext=image.ext)
                        )
            if slide_blocks:
                blocks.append(Block("page", text=f"幻灯片 {number}"))
                blocks.extend(slide_blocks)
        if not blocks:
            raise ParseError("未提取到内容")
        title = (
            clean_text(str(presentation.core_properties.title or ""))[:200]
            or Path(filename).stem
        )
        return ParsedDocument(title=title, blocks=blocks)
    except ParseError:
        raise
    except Exception as exc:
        logger.warning("PPTX parse failed: %s", filename, exc_info=True)
        raise ParseError("PPTX 解析失败") from exc
