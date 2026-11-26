import io
import logging
from pathlib import Path

import pdfplumber

from agentlab.config import Settings
from agentlab.parsing.base import (
    Block,
    ParsedDocument,
    ParseError,
    clean_text,
    table_to_markdown,
)

logger = logging.getLogger(__name__)


def _title(metadata: dict | None, filename: str) -> str:
    raw = clean_text(str((metadata or {}).get("Title") or ""))[:200]
    if raw and raw.lower() not in {"untitled", "(anonymous)"}:
        return raw
    return Path(filename).stem


def _page_content(page) -> tuple[str, list[list[list[str | None]]]]:
    tables = page.find_tables(
        table_settings={"vertical_strategy": "lines", "horizontal_strategy": "lines"}
    )
    bboxes = [table.bbox for table in tables]
    if bboxes:
        def outside_table(obj):
            if obj.get("object_type") != "char":
                return True
            x0, x1 = obj.get("x0", 0), obj.get("x1", 0)
            top, bottom = obj.get("top", 0), obj.get("bottom", 0)
            return not any(
                x0 >= bx0 and x1 <= bx1 and top >= btop and bottom <= bbottom
                for bx0, btop, bx1, bbottom in bboxes
            )

        text = page.filter(outside_table).extract_text() or ""
    else:
        text = page.extract_text() or ""
    rows: list[list[list[str | None]]] = []
    for table in tables:
        try:
            rows.append(table.extract())
        except Exception:
            logger.warning("table extraction failed", exc_info=True)
    return text, rows


def _parse_pages(pdf: pdfplumber.PDF, filename: str, settings: Settings) -> ParsedDocument:
    if len(pdf.pages) > settings.max_doc_pages:
        raise ParseError(f"PDF 页数超过 {settings.max_doc_pages} 页限制", 413)
    blocks: list[Block] = []
    for number, page in enumerate(pdf.pages, 1):
        raw_text, tables = _page_content(page)
        text = clean_text(raw_text)
        table_blocks = [
            markdown
            for markdown in (table_to_markdown(rows) for rows in tables)
            if markdown
        ]
        if not text and not table_blocks:
            continue
        blocks.append(Block("page", text=f"第 {number} 页"))
        if text:
            blocks.append(Block("text", text=text))
        for markdown in table_blocks:
            blocks.append(Block("table", text=markdown))
    if not blocks:
        raise ParseError("未提取到文字，可能是扫描件（暂不支持）")
    return ParsedDocument(title=_title(pdf.metadata, filename), blocks=blocks)


def parse_pdf(filename: str, data: bytes, settings: Settings) -> ParsedDocument:
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return _parse_pages(pdf, filename, settings)
    except ParseError:
        raise
    except Exception as exc:
        logger.warning("PDF parse failed: %s", filename, exc_info=True)
        raise ParseError("PDF 解析失败或已加密") from exc
