import io
import logging
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from agentlab.config import Settings
from agentlab.parsing.base import (
    Block,
    ParsedDocument,
    ParseError,
    clean_text,
    table_to_markdown,
)

logger = logging.getLogger(__name__)


# Only top-level paragraphs/tables are walked; content-control/SDT-wrapped
# content is a known P1 limitation (not flattened here).
def _iter_blocks(document):
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, document)
        elif child.tag == qn("w:tbl"):
            yield Table(child, document)


def _paragraph_markdown(paragraph: Paragraph) -> str:
    text = clean_text(paragraph.text)
    if not text:
        return ""
    style = (paragraph.style.name or "").lower()
    if style.startswith("heading"):
        try:
            level = int(style.split()[-1])
        except ValueError:
            level = 1
        level = min(max(level, 1), 6)
        return "#" * level + " " + text
    if "list" in style:
        return "- " + text
    return text


def _paragraph_images(paragraph: Paragraph, document) -> list[Block]:
    blocks: list[Block] = []
    for blip in paragraph._p.iter(qn("a:blip")):
        rid = blip.get(qn("r:embed"))
        if not rid:
            continue
        part = document.part.related_parts.get(rid)
        if part is None:
            continue
        ext = Path(str(part.partname)).suffix.lstrip(".") or "png"
        blocks.append(Block("image", image=part.blob, image_ext=ext))
    return blocks


def parse_docx(filename: str, data: bytes, settings: Settings) -> ParsedDocument:
    try:
        document = Document(io.BytesIO(data))
        blocks: list[Block] = []
        for item in _iter_blocks(document):
            if isinstance(item, Paragraph):
                markdown = _paragraph_markdown(item)
                if markdown:
                    blocks.append(Block("text", text=markdown))
                blocks.extend(_paragraph_images(item, document))
            elif isinstance(item, Table):
                rows = [[cell.text for cell in row.cells] for row in item.rows]
                markdown = table_to_markdown(rows)
                if markdown:
                    blocks.append(Block("table", text=markdown))
        if not blocks:
            raise ParseError("未提取到内容")
        title = (
            clean_text(str(document.core_properties.title or ""))[:200]
            or Path(filename).stem
        )
        return ParsedDocument(title=title, blocks=blocks)
    except ParseError:
        raise
    except Exception as exc:
        logger.warning("DOCX parse failed: %s", filename, exc_info=True)
        raise ParseError("DOCX 解析失败") from exc
