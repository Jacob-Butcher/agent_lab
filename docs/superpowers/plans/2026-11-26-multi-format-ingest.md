# 多格式知识库入库（P1）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 agent-lab 知识库支持 `.txt/.pdf/.docx/.pptx` 上传，解析为规范化 Markdown 后复用现有切块/向量化/检索链路；文档内图片用 DashScope `qwen-vl-ocr` 提取文字。

**Architecture:** 新增 `agentlab.parsing` 包（每种格式一个 converter + 组装器 + 图片 OCR），由 `KBManager.upload` 按扩展名分派；规范化产物写入 `uploads/<doc_id>.md`，原件与图片分别落 `uploads/.raw/` 与 `uploads/.assets/`，现有扫描/索引/覆盖/回退逻辑不变。

**Tech Stack:** Python 3.12 / uv、pdfplumber、python-docx、python-pptx、Pillow、charset-normalizer、filetype、FastAPI、langchain-openai（qwen-vl-ocr）、pytest（asyncio_mode=auto）。

**Spec:** `docs/superpowers/specs/2026-11-26-multi-format-ingest-design.md`

---

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `pyproject.toml` / `uv.lock` | 修改 | 新增解析依赖与测试依赖 |
| `src/agentlab/config.py` | 修改 | 上传上限 50MB + 解析/OCR/zip 配置 |
| `src/agentlab/parsing/base.py` | 新建 | `Block` / `ParsedDocument` / `ParseError` / 文本与表格工具 / 格式与 zip 校验 |
| `src/agentlab/parsing/text.py` | 新建 | TXT 解析 |
| `src/agentlab/parsing/pdf.py` | 新建 | PDF 解析（按页 + 表格） |
| `src/agentlab/parsing/docx.py` | 新建 | DOCX 解析（标题/段落/表格/图片，按文档流顺序） |
| `src/agentlab/parsing/pptx.py` | 新建 | PPTX 解析（每页 + 表格 + 图片） |
| `src/agentlab/parsing/images.py` | 新建 | 图片尺寸过滤/转码、DashScope OCR、`build_ocr` |
| `src/agentlab/parsing/assemble.py` | 新建 | blocks → 规范化 Markdown（异步 OCR 插入、去重） |
| `src/agentlab/parsing/__init__.py` | 新建 | `parse_document` 统一入口与导出 |
| `src/agentlab/kb.py` | 修改 | 上传分派、原件/图片落盘、删除清理、响应加 format |
| `src/agentlab/api/kb.py` | 修改 | 可选 `doc_id` 表单字段透传 |
| `static/admin/kb.html` | 修改 | 接受多格式、可选 doc_id 输入 |
| `tests/docgen.py` | 新建 | 测试用 DOCX/PPTX/PDF/PNG 生成器 |
| `tests/test_config.py` | 修改 | 新配置默认值 |
| `tests/test_parsing_base.py` | 新建 | 工具、格式校验、zip 限制 |
| `tests/test_parsing_txt.py` | 新建 | TXT 编码/空内容 |
| `tests/test_parsing_pdf.py` | 新建 | 页标题/表格/扫描件拒绝 |
| `tests/test_parsing_docx.py` | 新建 | 标题/段落/表格/图片 |
| `tests/test_parsing_pptx.py` | 新建 | 幻灯片/表格/图片 |
| `tests/test_parsing_assemble.py` | 新建 | 页标题/OCR 插入/去重/失败降级 |
| `tests/test_kb_formats.py` | 新建 | KBManager 多格式端到端 |
| `tests/test_kb_api.py` | 修改 | 多格式上传、doc_id、错误码；更新旧断言 |
| `tests/test_kb.py` | 修改 | 保持兼容（无行为变化） |
| `.env.example` / `README.md` | 修改 | 新配置与支持格式说明 |

---

## Task 1: 依赖与配置

**Files:**
- Modify: `pyproject.toml` / `uv.lock`
- Modify: `src/agentlab/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: 添加依赖**

```bash
uv add pdfplumber python-docx python-pptx filetype pillow charset-normalizer
uv add --group dev reportlab
```

Expected: 依赖写入 `pyproject.toml`，`uv.lock` 更新。若 PyPI 网络慢，重试一次 `uv add ... --default-index https://pypi.tuna.tsinghua.edu.cn/simple`。

- [ ] **Step 2: 写失败测试**

在 `tests/test_config.py` 末尾追加（并把已有的 `test_kb_defaults` 中 `max_upload_bytes` 断言改为 50MB）：

```python
def test_document_parsing_defaults():
    s = _settings()
    assert s.max_upload_bytes == 50 * 1024 * 1024
    assert s.max_doc_pages == 100
    assert s.max_doc_chars == 2_000_000
    assert s.image_ocr_enabled is True
    assert s.ocr_model == "qwen-vl-ocr"
    assert s.max_zip_uncompressed == 200 * 1024 * 1024
    assert s.max_zip_entries == 5000
```

- [ ] **Step 3: 运行确认失败**

Run: `uv run pytest tests/test_config.py -q`
Expected: FAIL（新属性不存在 / `max_upload_bytes` 仍是 2MB）

- [ ] **Step 4: 修改 `src/agentlab/config.py`**

把 `max_upload_bytes: int = 2 * 1024 * 1024` 改为：

```python
    max_upload_bytes: int = 50 * 1024 * 1024
```

在 `demo_dir: str = "demo"` 之前插入：

```python
    max_doc_pages: int = 100
    max_doc_chars: int = 2_000_000
    image_ocr_enabled: bool = True
    ocr_model: str = "qwen-vl-ocr"
    max_zip_uncompressed: int = 200 * 1024 * 1024
    max_zip_entries: int = 5000
```

- [ ] **Step 5: 运行确认通过**

Run: `uv run pytest tests/test_config.py -q` and `uv run ruff check src/agentlab/config.py tests/test_config.py`
Expected: PASS，ruff 干净

- [ ] **Step 6: 提交**

```bash
git add pyproject.toml uv.lock src/agentlab/config.py tests/test_config.py
git commit -m "feat: add multi-format ingest dependencies and settings"
```

---

## Task 2: 解析基础类型与工具

**Files:**
- Create: `src/agentlab/parsing/__init__.py`（本任务先留空导出语义，Task 8 补全）
- Create: `src/agentlab/parsing/base.py`
- Create: `tests/docgen.py`
- Test: `tests/test_parsing_base.py`

- [ ] **Step 1: 创建包入口文件**

创建 `src/agentlab/parsing/__init__.py`：

```python
"""Document parsers for multi-format knowledge-base ingestion."""
```

创建空的 `tests/__init__.py`（让测试可以 `from tests.docgen import ...`）：

```python
```

（文件内容为空即可。）

- [ ] **Step 2: 写失败测试**

创建 `tests/test_parsing_base.py`：

```python
import io
import zipfile

import pytest

from agentlab.config import Settings
from agentlab.parsing.base import (
    ParseError,
    clean_text,
    detect_format,
    table_to_markdown,
)


def _settings(**kwargs):
    return Settings(_env_file=None, **kwargs)


def test_clean_text_strips_controls_and_extra_blank_lines():
    assert clean_text("a\r\n\r\n\r\n\r\nb\x00c") == "a\n\nb c"
    assert clean_text("  \n\n  ") == ""


def test_table_to_markdown_escapes_and_pads():
    rows = [["类型", "时效"], ["无理由|退货", "7 天"], ["单列"]]
    md = table_to_markdown(rows)
    assert md.splitlines()[0] == "| 类型 | 时效 |"
    assert md.splitlines()[1] == "| --- | --- |"
    assert "| 无理由\\|退货 | 7 天 |" in md
    assert "| 单列 |  |" in md
    assert table_to_markdown([["only"]]) == ""


def test_detect_format_rejects_unknown_extension():
    with pytest.raises(ParseError) as exc:
        detect_format("a.csv", b"a,b\n1,2", _settings())
    assert exc.value.status == 400


def test_detect_format_rejects_pdf_disguised_as_docx():
    with pytest.raises(ParseError) as exc:
        detect_format("a.docx", b"%PDF-1.4\n", _settings())
    assert exc.value.status == 400


def test_detect_format_rejects_zip_bomb(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", "x" * 4096)
    settings = _settings(max_zip_uncompressed=1024)
    with pytest.raises(ParseError) as exc:
        detect_format("a.docx", buffer.getvalue(), settings)
    assert exc.value.status == 413


def test_detect_format_accepts_real_docx():
    from tests.docgen import make_docx

    assert detect_format("a.docx", make_docx(), _settings()) == "docx"
```

- [ ] **Step 3: 运行确认失败**

Run: `uv run pytest tests/test_parsing_base.py -q`
Expected: FAIL（`ModuleNotFoundError: agentlab.parsing.base`）

- [ ] **Step 4: 创建 `tests/docgen.py`**

```python
import io

from docx import Document
from docx.shared import Inches
from PIL import Image
from pptx import Presentation
from pptx.util import Inches as PptxInches
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Table, TableStyle


def png_bytes(width: int = 200, height: int = 100, color=(200, 30, 30)) -> bytes:
    image = Image.new("RGB", (width, height), color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def make_docx() -> bytes:
    document = Document()
    document.add_heading("退款政策", level=1)
    document.add_paragraph("订单签收后 7 天内可申请无理由退货。")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "类型"
    table.cell(0, 1).text = "时效"
    table.cell(1, 0).text = "无理由"
    table.cell(1, 1).text = "7 天"
    document.add_picture(io.BytesIO(png_bytes()), width=Inches(2))
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def make_pptx() -> bytes:
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[5])
    slide.shapes.title.text = "售后培训"
    box = slide.shapes.add_textbox(
        PptxInches(1), PptxInches(1), PptxInches(4), PptxInches(1)
    )
    box.text_frame.text = "退款 3 到 7 个工作日到账。"
    table = slide.shapes.add_table(
        2, 2, PptxInches(1), PptxInches(2.5), PptxInches(4), PptxInches(1)
    ).table
    table.cell(0, 0).text = "类型"
    table.cell(0, 1).text = "时效"
    table.cell(1, 0).text = "退款"
    table.cell(1, 1).text = "7 天"
    slide.shapes.add_picture(
        io.BytesIO(png_bytes()), PptxInches(1), PptxInches(4), width=PptxInches(1)
    )
    buffer = io.BytesIO()
    presentation.save(buffer)
    return buffer.getvalue()


def make_pdf() -> bytes:
    buffer = io.BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    table = Table([["Type", "Window"], ["No reason", "7 days"]])
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 1, colors.black)]))
    document.build(
        [
            Paragraph("Refund Policy", styles["Title"]),
            table,
            PageBreak(),
            Paragraph("Second page text", styles["Normal"]),
        ]
    )
    return buffer.getvalue()
```

- [ ] **Step 5: 创建 `src/agentlab/parsing/base.py`**

```python
import hashlib
import io
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import filetype

from agentlab.config import Settings

FORMAT_EXTENSIONS = {
    ".md": "md",
    ".txt": "txt",
    ".pdf": "pdf",
    ".docx": "docx",
    ".pptx": "pptx",
}
SUPPORTED_EXTENSIONS = tuple(FORMAT_EXTENSIONS)


class ParseError(Exception):
    def __init__(self, detail: str, status: int = 400) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status = status


@dataclass(frozen=True)
class Block:
    kind: Literal["text", "table", "page", "image"]
    text: str = ""
    image: bytes | None = None
    image_ext: str = "png"


@dataclass
class ParsedDocument:
    title: str
    blocks: list[Block] = field(default_factory=list)


def clean_text(text: str) -> str:
    cleaned = "".join(ch for ch in text if ch in "\n\t" or ord(ch) >= 32)
    while "\n\n\n" in cleaned:
        cleaned = cleaned.replace("\n\n\n", "\n\n")
    return cleaned.strip()


def table_to_markdown(rows: list[list[str | None]]) -> str:
    cleaned: list[list[str]] = []
    for row in rows:
        cells = [
            ("" if cell is None else str(cell))
            .replace("|", "\\|")
            .replace("\n", "<br>")
            .strip()
            for cell in row
        ]
        if any(cells):
            cleaned.append(cells)
    if len(cleaned) < 2:
        return ""
    width = max(len(row) for row in cleaned)
    cleaned = [row + [""] * (width - len(row)) for row in cleaned]
    lines = [
        "| " + " | ".join(cleaned[0]) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    for row in cleaned[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _open_zip(data: bytes, settings: Settings) -> zipfile.ZipFile:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ParseError("文件损坏或不是有效的 Office 文档") from exc
    infos = archive.infolist()
    if len(infos) > settings.max_zip_entries:
        raise ParseError("文档解压条目过多，已拒绝", 413)
    if sum(info.file_size for info in infos) > settings.max_zip_uncompressed:
        raise ParseError("文档解压后体积过大，已拒绝", 413)
    return archive


def detect_format(filename: str, data: bytes, settings: Settings) -> str:
    kind = FORMAT_EXTENSIONS.get(Path(filename).suffix.lower())
    if kind is None or kind == "md":
        raise ParseError("不支持的文件类型，仅支持 .md/.txt/.pdf/.docx/.pptx")
    guessed = filetype.guess(data)
    if kind == "pdf":
        if guessed is None or guessed.extension != "pdf":
            raise ParseError("文件内容与扩展名不符")
    elif kind in {"docx", "pptx"}:
        with _open_zip(data, settings) as archive:
            prefix = "word/" if kind == "docx" else "ppt/"
            if not any(name.startswith(prefix) for name in archive.namelist()):
                raise ParseError("文件内容与扩展名不符")
    return kind
```

- [ ] **Step 6: 运行确认通过**

Run: `uv run pytest tests/test_parsing_base.py tests/test_config.py -q` and `uv run ruff check src/agentlab/parsing tests/docgen.py tests/test_parsing_base.py`
Expected: PASS，ruff 干净

- [ ] **Step 7: 提交**

```bash
git add src/agentlab/parsing/__init__.py src/agentlab/parsing/base.py tests/docgen.py tests/test_parsing_base.py
git commit -m "feat: add parsing base types and format detection"
```

---

## Task 3: TXT 解析

**Files:**
- Create: `src/agentlab/parsing/text.py`
- Test: `tests/test_parsing_txt.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_parsing_txt.py`：

```python
import pytest

from agentlab.config import Settings
from agentlab.parsing.base import ParseError
from agentlab.parsing.text import parse_txt


def _settings():
    return Settings(_env_file=None)


def test_parse_txt_utf8():
    doc = parse_txt("退款.txt", "第一段。\n\n第二段。".encode("utf-8"), _settings())
    assert doc.title == "退款"
    assert doc.blocks[0].kind == "text"
    assert "第二段" in doc.blocks[0].text


def test_parse_txt_gbk():
    doc = parse_txt("政策.txt", "售后政策".encode("gbk"), _settings())
    assert "售后政策" in doc.blocks[0].text


def test_parse_txt_rejects_empty_and_binary():
    with pytest.raises(ParseError):
        parse_txt("empty.txt", b"   ", _settings())
    with pytest.raises(ParseError):
        parse_txt("bin.txt", b"a\x00b", _settings())
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_parsing_txt.py -q`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 创建 `src/agentlab/parsing/text.py`**

```python
from pathlib import Path

from charset_normalizer import from_bytes

from agentlab.config import Settings
from agentlab.parsing.base import Block, ParsedDocument, ParseError, clean_text


def parse_txt(filename: str, data: bytes, settings: Settings) -> ParsedDocument:
    if b"\x00" in data:
        raise ParseError("不是有效的文本文件")
    best = from_bytes(data).best()
    text = str(best) if best is not None else data.decode("utf-8", errors="replace")
    body = clean_text(text)
    if not body:
        raise ParseError("文本内容为空")
    return ParsedDocument(
        title=Path(filename).stem,
        blocks=[Block("text", text=body)],
    )
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_parsing_txt.py -q`
Expected: PASS（3 个测试）

- [ ] **Step 5: 提交**

```bash
git add src/agentlab/parsing/text.py tests/test_parsing_txt.py
git commit -m "feat: add plain text parser"
```

---

## Task 4: PDF 解析

**Files:**
- Create: `src/agentlab/parsing/pdf.py`
- Test: `tests/test_parsing_pdf.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_parsing_pdf.py`：

```python
import pytest

from agentlab.config import Settings
from agentlab.parsing.base import ParseError
from agentlab.parsing.pdf import parse_pdf
from tests.docgen import make_pdf


def _settings(**kwargs):
    return Settings(_env_file=None, **kwargs)


def test_parse_pdf_pages_and_table():
    doc = parse_pdf("refund.pdf", make_pdf(), _settings())
    kinds = [block.kind for block in doc.blocks]
    assert "page" in kinds and "table" in kinds
    assert doc.blocks[0].text == "第 1 页"
    assert any("Second page text" in block.text for block in doc.blocks)
    assert any("| Type | Window |" in block.text for block in doc.blocks)
    assert doc.title == "refund"


def test_parse_pdf_rejects_page_limit():
    settings = _settings(max_doc_pages=1)
    with pytest.raises(ParseError) as exc:
        parse_pdf("refund.pdf", make_pdf(), settings)
    assert exc.value.status == 413


def test_parse_pdf_rejects_empty_text():
    # 一个只有图片的 PDF 无法用简单方式构造；用损坏内容验证错误路径
    with pytest.raises(ParseError):
        parse_pdf("bad.pdf", b"%PDF-1.4 broken", _settings())
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_parsing_pdf.py -q`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 创建 `src/agentlab/parsing/pdf.py`**

```python
import io
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


def _title(metadata: dict | None, filename: str) -> str:
    raw = str((metadata or {}).get("Title") or "").strip()
    if raw and raw.lower() != "untitled":
        return raw
    return Path(filename).stem


def _parse_pages(
    pdf, filename: str, settings: Settings
) -> ParsedDocument:
    if len(pdf.pages) > settings.max_doc_pages:
        raise ParseError(f"PDF 页数超过 {settings.max_doc_pages} 页限制", 413)
    blocks: list[Block] = []
    has_content = False
    for number, page in enumerate(pdf.pages, 1):
        text = clean_text(page.extract_text() or "")
        tables = [
            markdown
            for markdown in (
                table_to_markdown(rows)
                for rows in (page.extract_tables() or [])
            )
            if markdown
        ]
        if not text and not tables:
            continue
        blocks.append(Block("page", text=f"第 {number} 页"))
        if text:
            blocks.append(Block("text", text=text))
            has_content = True
        for markdown in tables:
            blocks.append(Block("table", text=markdown))
            has_content = True
    if not has_content:
        raise ParseError("未提取到文字，可能是扫描件（暂不支持）")
    return ParsedDocument(title=_title(pdf.metadata, filename), blocks=blocks)


def parse_pdf(filename: str, data: bytes, settings: Settings) -> ParsedDocument:
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return _parse_pages(pdf, filename, settings)
    except ParseError:
        raise
    except Exception as exc:
        raise ParseError("PDF 解析失败或已加密") from exc
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_parsing_pdf.py -q`
Expected: PASS（3 个测试）

- [ ] **Step 5: 提交**

```bash
git add src/agentlab/parsing/pdf.py tests/test_parsing_pdf.py
git commit -m "feat: add PDF text and table parser"
```

---

## Task 5: DOCX 解析

**Files:**
- Create: `src/agentlab/parsing/docx.py`
- Test: `tests/test_parsing_docx.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_parsing_docx.py`：

```python
from agentlab.config import Settings
from agentlab.parsing.docx import parse_docx
from tests.docgen import make_docx


def _settings():
    return Settings(_env_file=None)


def test_parse_docx_heading_paragraph_table_and_image():
    doc = parse_docx("refund.docx", make_docx(), _settings())
    texts = [block.text for block in doc.blocks if block.kind == "text"]
    assert any(text.startswith("# 退款政策") for text in texts)
    assert any("7 天内" in text for text in texts)
    assert any(block.kind == "table" and "| 类型 | 时效 |" in block.text for block in doc.blocks)
    images = [block for block in doc.blocks if block.kind == "image"]
    assert images and images[0].image


def test_parse_docx_title_falls_back_to_filename():
    doc = parse_docx("售后手册.docx", make_docx(), _settings())
    assert doc.title in {"退款政策", "售后手册"}
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_parsing_docx.py -q`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 创建 `src/agentlab/parsing/docx.py`**

```python
import io
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
    except Exception as exc:
        raise ParseError("DOCX 解析失败") from exc
    blocks: list[Block] = []
    for item in _iter_blocks(document):
        if isinstance(item, Paragraph):
            markdown = _paragraph_markdown(item)
            if markdown:
                blocks.append(Block("text", text=markdown))
            blocks.extend(_paragraph_images(item, document))
        else:
            rows = [[cell.text for cell in row.cells] for row in item.rows]
            markdown = table_to_markdown(rows)
            if markdown:
                blocks.append(Block("table", text=markdown))
    if not any(block.kind in ("text", "table", "image") for block in blocks):
        raise ParseError("未提取到内容")
    title = (document.core_properties.title or "").strip() or Path(filename).stem
    return ParsedDocument(title=title, blocks=blocks)
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_parsing_docx.py -q`
Expected: PASS（2 个测试）

- [ ] **Step 5: 提交**

```bash
git add src/agentlab/parsing/docx.py tests/test_parsing_docx.py
git commit -m "feat: add DOCX parser"
```

---

## Task 6: PPTX 解析

**Files:**
- Create: `src/agentlab/parsing/pptx.py`
- Test: `tests/test_parsing_pptx.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_parsing_pptx.py`：

```python
from agentlab.config import Settings
from agentlab.parsing.pptx import parse_pptx
from tests.docgen import make_pptx


def _settings():
    return Settings(_env_file=None)


def test_parse_pptx_slides_table_and_image():
    doc = parse_pptx("training.pptx", make_pptx(), _settings())
    pages = [block.text for block in doc.blocks if block.kind == "page"]
    assert pages == ["幻灯片 1"]
    assert any("退款 3 到 7" in block.text for block in doc.blocks)
    assert any(block.kind == "table" and "| 类型 | 时效 |" in block.text for block in doc.blocks)
    images = [block for block in doc.blocks if block.kind == "image"]
    assert images and images[0].image
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_parsing_pptx.py -q`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 创建 `src/agentlab/parsing/pptx.py`**

```python
import io
from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from agentlab.config import Settings
from agentlab.parsing.base import (
    Block,
    ParsedDocument,
    ParseError,
    clean_text,
    table_to_markdown,
)


def _table_rows(shape) -> list[list[str]]:
    return [[cell.text for cell in row.cells] for row in shape.table.rows]


def parse_pptx(filename: str, data: bytes, settings: Settings) -> ParsedDocument:
    try:
        presentation = Presentation(io.BytesIO(data))
    except Exception as exc:
        raise ParseError("PPTX 解析失败") from exc
    slides = list(presentation.slides)
    if len(slides) > settings.max_doc_pages:
        raise ParseError(f"幻灯片数量超过 {settings.max_doc_pages} 页限制", 413)
    blocks: list[Block] = []
    for number, slide in enumerate(slides, 1):
        slide_blocks: list[Block] = []
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
                markdown = table_to_markdown(_table_rows(shape))
                if markdown:
                    slide_blocks.append(Block("table", text=markdown))
            elif shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                try:
                    image = shape.image
                except Exception:
                    continue
                slide_blocks.append(Block("image", image=image.blob, image_ext=image.ext))
        if slide_blocks:
            blocks.append(Block("page", text=f"幻灯片 {number}"))
            blocks.extend(slide_blocks)
    if not any(block.kind != "page" for block in blocks):
        raise ParseError("未提取到内容")
    title = (presentation.core_properties.title or "").strip() or Path(filename).stem
    return ParsedDocument(title=title, blocks=blocks)
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_parsing_pptx.py -q`
Expected: PASS（1 个测试）

- [ ] **Step 5: 提交**

```bash
git add src/agentlab/parsing/pptx.py tests/test_parsing_pptx.py
git commit -m "feat: add PPTX parser"
```

---

## Task 7: 图片处理与 OCR

**Files:**
- Create: `src/agentlab/parsing/images.py`
- Test: `tests/test_parsing_images.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_parsing_images.py`：

```python
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
    assert image_digest(data) == image_digest(data)


def test_build_ocr_disabled_or_without_key():
    assert build_ocr(_settings(image_ocr_enabled=False, dashscope_api_key="x")) is None
    assert build_ocr(_settings(image_ocr_enabled=True, dashscope_api_key="")) is None
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_parsing_images.py -q`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 创建 `src/agentlab/parsing/images.py`**

```python
import base64
import hashlib
import io
import logging
from typing import Protocol

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from PIL import Image

from agentlab.config import Settings

logger = logging.getLogger(__name__)

MIN_DIMENSION = 100
MAX_DIMENSION = 2048
MAX_IMAGE_BYTES = 10 * 1024 * 1024
OCR_PROMPT = "请提取图片中的全部文字，保持原有换行与结构，不要解释。"


class ImageOcr(Protocol):
    async def extract(self, image: bytes) -> str: ...


def prepare_image(data: bytes) -> tuple[bytes, str] | None:
    if not data or len(data) > MAX_IMAGE_BYTES:
        return None
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            if image.width < MIN_DIMENSION or image.height < MIN_DIMENSION:
                return None
            converted = image.convert("RGB")
            if max(converted.size) > MAX_DIMENSION:
                converted.thumbnail((MAX_DIMENSION, MAX_DIMENSION))
            buffer = io.BytesIO()
            converted.save(buffer, format="PNG")
            return buffer.getvalue(), "png"
    except Exception:
        logger.warning("skip unsupported image", exc_info=True)
        return None


def image_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class DashScopeImageOcr:
    def __init__(self, settings: Settings) -> None:
        self.llm = ChatOpenAI(
            model=settings.ocr_model,
            api_key=settings.dashscope_api_key,
            base_url=settings.dashscope_base_url,
            timeout=30,
            max_retries=0,
        )

    async def extract(self, image: bytes) -> str:
        data_url = "data:image/png;base64," + base64.b64encode(image).decode("ascii")
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
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            ).strip()
        return ""


def build_ocr(settings: Settings) -> ImageOcr | None:
    if not settings.image_ocr_enabled or not settings.dashscope_api_key:
        return None
    return DashScopeImageOcr(settings)
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_parsing_images.py -q`
Expected: PASS（3 个测试）

- [ ] **Step 5: 提交**

```bash
git add src/agentlab/parsing/images.py tests/test_parsing_images.py
git commit -m "feat: add image preparation and DashScope OCR client"
```

---

## Task 8: 组装器与统一入口

**Files:**
- Create: `src/agentlab/parsing/assemble.py`
- Modify: `src/agentlab/parsing/__init__.py`
- Test: `tests/test_parsing_assemble.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_parsing_assemble.py`：

```python
import pytest

from agentlab.config import Settings
from agentlab.parsing.assemble import assemble
from agentlab.parsing.base import Block, ParseError, ParsedDocument
from tests.docgen import make_docx, png_bytes


def _settings(**kwargs):
    return Settings(_env_file=None, **kwargs)


class FakeOcr:
    def __init__(self, text: str = "发票抬头：星选商城", fail: bool = False) -> None:
        self.text = text
        self.fail = fail
        self.calls = 0

    async def extract(self, image: bytes) -> str:
        self.calls += 1
        if self.fail:
            raise RuntimeError("ocr down")
        return self.text


async def test_assemble_pages_text_and_ocr():
    image = png_bytes(200, 100)
    document = ParsedDocument(
        "t",
        [
            Block("page", text="第 1 页"),
            Block("text", text="正文内容"),
            Block("image", image=image, image_ext="png"),
            Block("image", image=image, image_ext="png"),
            Block("image", image=png_bytes(50, 50), image_ext="png"),
        ],
    )
    ocr = FakeOcr()
    result = await assemble(document, ocr, _settings())

    assert result.markdown.startswith("## 第 1 页")
    assert "正文内容" in result.markdown
    assert "> 图片文字：发票抬头：星选商城" in result.markdown
    assert len(result.assets) == 1
    assert ocr.calls == 1


async def test_assemble_survives_ocr_failure():
    document = ParsedDocument(
        "t",
        [Block("text", text="正文内容"), Block("image", image=png_bytes(200, 100))],
    )
    result = await assemble(document, FakeOcr(fail=True), _settings())
    assert "正文内容" in result.markdown
    assert "图片文字" not in result.markdown


async def test_assemble_rejects_empty_and_too_large():
    with pytest.raises(ParseError):
        await assemble(ParsedDocument("t", [Block("text", text="   ")]), None, _settings())
    with pytest.raises(ParseError) as exc:
        await assemble(
            ParsedDocument("t", [Block("text", text="x" * 20)]),
            None,
            _settings(max_doc_chars=10),
        )
    assert exc.value.status == 413


def test_parse_document_dispatch():
    from agentlab.parsing import parse_document

    kind, parsed = parse_document("a.docx", make_docx(), _settings())
    assert kind == "docx"
    assert parsed.title
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_parsing_assemble.py -q`
Expected: FAIL（模块/入口不存在）

- [ ] **Step 3: 创建 `src/agentlab/parsing/assemble.py`**

```python
import logging
from dataclasses import dataclass

from agentlab.config import Settings
from agentlab.parsing.base import ParsedDocument, ParseError, clean_text
from agentlab.parsing.images import ImageOcr, image_digest, prepare_image

logger = logging.getLogger(__name__)


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
    seen: set[str] = set()
    index = 0
    for block in document.blocks:
        if block.kind == "page":
            if block.text:
                parts.append(f"## {block.text}")
        elif block.kind in ("text", "table"):
            text = clean_text(block.text)
            if text:
                parts.append(text)
        elif block.kind == "image":
            prepared = prepare_image(block.image or b"")
            if prepared is None:
                continue
            data, ext = prepared
            digest = image_digest(data)
            if digest in seen:
                continue
            seen.add(digest)
            index += 1
            assets.append(Asset(name=f"image-{index:02d}.{ext}", data=data))
            if ocr is not None:
                try:
                    text = clean_text(await ocr.extract(data))
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
        raise ParseError("未提取到可入库内容")
    return Assembled(markdown=markdown, assets=assets)
```

- [ ] **Step 4: 补全 `src/agentlab/parsing/__init__.py`**

```python
"""Document parsers for multi-format knowledge-base ingestion."""

from agentlab.config import Settings
from agentlab.parsing.base import ParseError, ParsedDocument, detect_format
from agentlab.parsing.docx import parse_docx
from agentlab.parsing.pdf import parse_pdf
from agentlab.parsing.pptx import parse_pptx
from agentlab.parsing.text import parse_txt

PARSERS = {
    "txt": parse_txt,
    "pdf": parse_pdf,
    "docx": parse_docx,
    "pptx": parse_pptx,
}


def parse_document(
    filename: str, data: bytes, settings: Settings
) -> tuple[str, ParsedDocument]:
    kind = detect_format(filename, data, settings)
    parser = PARSERS.get(kind)
    if parser is None:
        raise ParseError("不支持的文件类型")
    return kind, parser(filename, data, settings)
```

- [ ] **Step 5: 运行确认通过**

Run: `uv run pytest tests/test_parsing_assemble.py -q` and `uv run ruff check src/agentlab/parsing tests/test_parsing_assemble.py`
Expected: PASS（4 个测试），ruff 干净

- [ ] **Step 6: 提交**

```bash
git add src/agentlab/parsing/assemble.py src/agentlab/parsing/__init__.py tests/test_parsing_assemble.py
git commit -m "feat: assemble parsed blocks into normalized markdown"
```

---

## Task 9: KBManager 集成

**Files:**
- Modify: `src/agentlab/kb.py`
- Test: `tests/test_kb_formats.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_kb_formats.py`：

```python
import pytest

from agentlab.config import Settings
from agentlab.kb import KbError, KBManager
from agentlab.llm import HashEmbeddings
from agentlab.rag.store import InMemoryChunkStore
from tests.docgen import make_docx, make_pptx


class FakeOcr:
    async def extract(self, image: bytes) -> str:
        return "截图文字：退货需保持完好"


def _manager(tmp_path):
    settings = Settings(
        _env_file=None,
        model_provider="mock",
        memory_backend="memory",
        corpus_dir=str(tmp_path / "corpus"),
        upload_dir=str(tmp_path / "uploads"),
        max_upload_bytes=5 * 1024 * 1024,
    )
    (tmp_path / "corpus").mkdir()
    store = InMemoryChunkStore()
    return KBManager(settings, store, HashEmbeddings(64), ocr=FakeOcr()), store


async def test_upload_docx_stores_normalized_raw_and_assets(tmp_path):
    kb, _store = _manager(tmp_path)
    result = await kb.upload("refund.docx", make_docx())

    assert result["format"] == "docx"
    assert result["doc_id"].startswith("docx-")
    normalized = kb.upload_dir / f"{result['doc_id']}.md"
    assert normalized.is_file()
    text = normalized.read_text(encoding="utf-8")
    assert "source_format: docx" in text
    assert "# 退款政策" in text
    assert "| 类型 | 时效 |" in text
    assert "图片文字：截图文字" in text
    assert list((kb.upload_dir / ".raw").glob("*.docx"))
    assert list((kb.upload_dir / ".assets" / result["doc_id"]).glob("*.png"))


async def test_upload_pptx_and_optional_doc_id(tmp_path):
    kb, _store = _manager(tmp_path)
    result = await kb.upload("training.pptx", make_pptx(), doc_id="training-pptx")
    assert result["doc_id"] == "training-pptx"
    assert result["format"] == "pptx"


async def test_upload_document_conflict_and_overwrite(tmp_path):
    kb, _store = _manager(tmp_path)
    await kb.upload("refund.docx", make_docx())
    with pytest.raises(KbError) as exc:
        await kb.upload("refund.docx", make_docx())
    assert exc.value.status == 409

    result = await kb.upload("refund.docx", make_docx(), overwrite=True)
    assert result["format"] == "docx"


async def test_delete_removes_raw_and_assets(tmp_path):
    kb, _store = _manager(tmp_path)
    result = await kb.upload("refund.docx", make_docx())
    doc_id = result["doc_id"]

    await kb.delete(doc_id)

    assert not (kb.upload_dir / f"{doc_id}.md").exists()
    assert not list((kb.upload_dir / ".raw").glob(f"{doc_id}.*"))
    assert not (kb.upload_dir / ".assets" / doc_id).exists()
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_kb_formats.py -q`
Expected: FAIL（`upload` 不接受 docx / 无 ocr 参数）

- [ ] **Step 3: 修改 `src/agentlab/kb.py`**

顶部导入增加：

```python
import shutil

from agentlab.parsing import ParseError, parse_document
from agentlab.parsing.assemble import Asset, assemble
from agentlab.parsing.base import sha256_bytes
from agentlab.parsing.images import ImageOcr, build_ocr
```

构造函数签名改为并增加 `self.ocr`：

```python
    def __init__(
        self,
        settings: Settings,
        store: ChunkStore,
        embeddings: Embeddings,
        ocr: ImageOcr | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.embeddings = embeddings
        self.corpus_dir = Path(settings.corpus_dir)
        self.upload_dir = Path(settings.upload_dir)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self.ocr = build_ocr(settings) if ocr is None else ocr
```

新增二进制原子写与源文件辅助方法（放在 `_write_atomic` 之后）：

```python
    @staticmethod
    def _write_bytes_atomic(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.stem}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.replace(tmp, path)
        finally:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass

    def _write_source(
        self, doc_id: str, suffix: str, data: bytes, assets: list[Asset]
    ) -> None:
        raw_dir = self.upload_dir / ".raw"
        self._write_bytes_atomic(raw_dir / f"{doc_id}{suffix}", data)
        asset_dir = self.upload_dir / ".assets" / doc_id
        shutil.rmtree(asset_dir, ignore_errors=True)
        if assets:
            asset_dir.mkdir(parents=True, exist_ok=True)
            for asset in assets:
                (asset_dir / asset.name).write_bytes(asset.data)

    def _remove_source_files(self, doc_id: str) -> None:
        raw_dir = self.upload_dir / ".raw"
        if raw_dir.is_dir():
            for path in raw_dir.glob(f"{doc_id}.*"):
                path.unlink(missing_ok=True)
        shutil.rmtree(self.upload_dir / ".assets" / doc_id, ignore_errors=True)
```

把现有 `upload` 拆成三个方法：`upload` 负责大小检查与分派；`_upload_markdown` 保留原有 md 逻辑（响应增加 `format`）；`_upload_document` 处理解析型文档。

```python
    async def upload(
        self,
        filename: str,
        data: bytes,
        overwrite: bool = False,
        doc_id: str | None = None,
    ) -> dict:
        if len(data) > self.settings.max_upload_bytes:
            raise KbError(413, f"文件超过 {self.settings.max_upload_bytes} 字节限制")
        if filename.lower().endswith(".md"):
            return await self._upload_markdown(filename, data, overwrite)
        return await self._upload_document(filename, data, overwrite, doc_id)

    async def _upload_markdown(
        self, filename: str, data: bytes, overwrite: bool
    ) -> dict:
```

`_upload_markdown` 的完整实现如下（此后接 `_upload_document`）：

```python
    async def _upload_markdown(
        self, filename: str, data: bytes, overwrite: bool
    ) -> dict:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise KbError(400, "文件必须是 UTF-8 编码") from exc

        try:
            post = frontmatter.loads(text)
        except Exception as exc:
            raise KbError(400, "frontmatter 解析失败，请检查 YAML 格式") from exc
        doc_id = str(post.metadata.get("doc_id") or Path(filename).stem)
        if not DOC_ID_PATTERN.match(doc_id):
            raise KbError(
                400, "doc_id 只能包含小写字母、数字、点、下划线、短横线，且不超过 64 字符"
            )
        title = str(post.metadata.get("title") or doc_id)
        body = post.content.strip()
        if not body:
            raise KbError(400, "文档正文为空")

        async with self._lock:
            existing = self._file_index().get(doc_id)
            if existing and not overwrite:
                raise KbError(409, f"doc_id 已存在：{doc_id}，是否覆盖？")
            chunks = list(split_markdown(body, doc_id, title))
            if not chunks:
                raise KbError(400, "文档切块后为空")

            post.content = body
            post.metadata["doc_id"] = doc_id
            post.metadata.setdefault("title", title)
            vectors = await self._embed(chunks)
            self._write_atomic(self._upload_path(doc_id), frontmatter.dumps(post))
            self._remove_stale_upload(doc_id)
            self._remove_source_files(doc_id)
            await self._save_index(doc_id, body, chunks, vectors)
            return {
                "doc_id": doc_id,
                "title": title,
                "chunks": len(chunks),
                "source": "uploads",
                "format": "md",
            }

    async def _upload_document(
        self,
        filename: str,
        data: bytes,
        overwrite: bool,
        doc_id_override: str | None,
    ) -> dict:
        try:
            kind, parsed = await asyncio.to_thread(
                parse_document, filename, data, self.settings
            )
            assembled = await assemble(parsed, self.ocr, self.settings)
        except ParseError as exc:
            raise KbError(exc.status, exc.detail) from exc
        except Exception as exc:
            raise KbError(400, "文档解析失败") from exc

        doc_id = doc_id_override or f"{kind}-{sha256_bytes(data)[:10]}"
        if not DOC_ID_PATTERN.match(doc_id):
            raise KbError(400, "doc_id 不合法")
        title = parsed.title or Path(filename).stem
        body = assembled.markdown
        chunks = list(split_markdown(body, doc_id, title))
        if not chunks:
            raise KbError(400, "文档切块后为空")

        post = frontmatter.Post(body)
        post.metadata = {
            "doc_id": doc_id,
            "title": title,
            "source_format": kind,
            "source_file": Path(filename).name,
        }
        text = frontmatter.dumps(post)

        async with self._lock:
            existing = self._file_index().get(doc_id)
            if existing and not overwrite:
                raise KbError(409, f"doc_id 已存在：{doc_id}，是否覆盖？")
            vectors = await self._embed(chunks)
            self._write_atomic(self._upload_path(doc_id), text)
            self._write_source(doc_id, Path(filename).suffix.lower(), data, assembled.assets)
            self._remove_stale_upload(doc_id)
            await self._save_index(doc_id, body, chunks, vectors)
            return {
                "doc_id": doc_id,
                "title": title,
                "chunks": len(chunks),
                "source": "uploads",
                "format": kind,
            }
```

在 `delete` 中，两个删除分支的 `upload_path.unlink()` 之后都增加：

```python
                self._remove_source_files(doc_id)
```

（两条分支各加一次；注意缩进对应。）

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_kb_formats.py tests/test_kb.py -q`
Expected: PASS（4 + 22 个测试）

- [ ] **Step 5: 运行 lint**

Run: `uv run ruff check src/agentlab/kb.py tests/test_kb_formats.py`
Expected: 干净

- [ ] **Step 6: 提交**

```bash
git add src/agentlab/kb.py tests/test_kb_formats.py
git commit -m "feat: ingest txt/pdf/docx/pptx through KB manager"
```

---

## Task 10: API 支持 doc_id 与 format

**Files:**
- Modify: `src/agentlab/api/kb.py`
- Modify: `tests/test_kb_api.py`

- [ ] **Step 1: 更新测试 fixture 与旧断言**

在 `tests/test_kb_api.py`：

1. `_make_app` 中 `max_upload_bytes=1024` 改为 `max_upload_bytes=5 * 1024 * 1024`。
2. `test_upload_rejects_oversized_file` 的 `b"x" * 2048` 改为 `b"x" * (5 * 1024 * 1024 + 1)`。
3. `test_put_rejects_oversized_body` 的 `read.json()["body"] + "x" * 2048` 改为 `+ "x" * (5 * 1024 * 1024)`。
4. `test_upload_rejects_non_markdown` 的文件名 `.txt` 改为 `.csv`（`.txt` 现在被支持）。

- [ ] **Step 2: 写新失败测试**

在 `tests/test_kb_api.py` 末尾追加：

```python
async def test_upload_docx_returns_format(tmp_path):
    from tests.docgen import make_docx

    app, services = await _make_app(tmp_path)
    try:
        async with _client(app) as client:
            response = await client.post(
                "/api/kb/docs",
                headers=HEADERS,
                files={
                    "file": (
                        "refund.docx",
                        make_docx(),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                },
            )
        assert response.status_code == 201
        payload = response.json()
        assert payload["format"] == "docx"
        assert payload["doc_id"].startswith("docx-")
    finally:
        await services.close()


async def test_upload_txt_with_optional_doc_id(tmp_path):
    app, services = await _make_app(tmp_path)
    try:
        async with _client(app) as client:
            response = await client.post(
                "/api/kb/docs",
                headers=HEADERS,
                data={"doc_id": "policy-txt"},
                files={"file": ("policy.txt", "售后政策".encode("utf-8"), "text/plain")},
            )
        assert response.status_code == 201
        assert response.json()["doc_id"] == "policy-txt"
        assert response.json()["format"] == "txt"
    finally:
        await services.close()


```

- [ ] **Step 3: 运行确认失败**

Run: `uv run pytest tests/test_kb_api.py -q`
Expected: FAIL（docx 上传 400 / 无 doc_id 表单）

- [ ] **Step 4: 修改 `src/agentlab/api/kb.py`**

导入增加 `Form`：

```python
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
```

上传端点改为：

```python
    @router.post("/docs", status_code=201)
    async def upload_doc(
        kb: Admin,
        file: Annotated[UploadFile, File()],
        overwrite: bool = False,
        doc_id: Annotated[str | None, Form()] = None,
    ):
        if not file.filename:
            raise KbError(400, "缺少文件名")
        data = await file.read(kb.settings.max_upload_bytes + 1)
        return await kb.upload(
            file.filename, data, overwrite=overwrite, doc_id=doc_id
        )
```

- [ ] **Step 5: 运行确认通过**

Run: `uv run pytest tests/test_kb_api.py -q`
Expected: PASS（17 个测试）

- [ ] **Step 6: 提交**

```bash
git add src/agentlab/api/kb.py tests/test_kb_api.py
git commit -m "feat: accept doc_id and report format in KB upload API"
```

---

## Task 11: 管理页支持多格式

**Files:**
- Modify: `static/admin/kb.html`
- Test: `tests/test_kb_api.py`（Step 2 的断言已在 Task 10 加入，本任务只需让页面满足）

- [ ] **Step 1: 修改文件输入与 doc_id 输入**

把：

```html
      <label style="color:var(--accent);cursor:pointer">点击选择<input type="file" id="file" accept=".md,text/markdown" hidden></label>
```

替换为：

```html
      <label style="color:var(--accent);cursor:pointer">点击选择<input type="file" id="file" accept=".md,.txt,.pdf,.docx,.pptx" hidden></label>
```

在 `#drop` 之后新增：

```html
    <div style="display:flex;gap:8px;margin-top:10px;align-items:center">
      <input id="doc-id" placeholder="可选 doc_id（ASCII，仅对非 md 生效）" style="flex:1;max-width:320px">
      <span class="muted">不填则自动生成「格式-内容哈希」</span>
    </div>
```

- [ ] **Step 2: 修改上传函数**

把 `handleFile` 的扩展名检查改为：

```js
  const allowed = [".md", ".txt", ".pdf", ".docx", ".pptx"];
  const name = file.name.toLowerCase();
  if (!allowed.some((ext) => name.endsWith(ext))) {
    toast("仅支持 .md/.txt/.pdf/.docx/.pptx 文件", true);
    return;
  }
```

把 `uploadFile` 改为：

```js
async function uploadFile(file, overwrite) {
  const form = new FormData();
  form.append("file", file);
  const docId = document.getElementById("doc-id").value.trim();
  if (docId) form.append("doc_id", docId);
  const url = "/api/kb/docs" + (overwrite ? "?overwrite=true" : "");
  return api(url, { method: "POST", body: form });
}
```

上传成功提示改为：

```js
    toast("已入库 " + result.doc_id + "（" + result.format + "，" + result.chunks + " 个片段）");
```

覆盖成功提示同理可保留原样。

- [ ] **Step 3: 添加页面内容测试**

在 `tests/test_kb_api.py` 末尾追加：

```python
async def test_admin_page_lists_document_accept_types(tmp_path):
    app, services = await _make_app(tmp_path)
    try:
        async with _client(app) as client:
            response = await client.get("/admin/kb")
        assert ".pdf" in response.text
        assert "doc_id" in response.text
    finally:
        await services.close()
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_kb_api.py -q`
Expected: PASS（18 个测试）

- [ ] **Step 5: 提交**

```bash
git add static/admin/kb.html tests/test_kb_api.py
git commit -m "feat: accept multi-format documents in KB admin page"
```

---

## Task 12: 配置示例与文档

**Files:**
- Modify: `.env.example`
- Modify: `README.md`

- [ ] **Step 1: 修改 `.env.example`**

把 `MAX_UPLOAD_BYTES=2097152` 改为：

```bash
MAX_UPLOAD_BYTES=52428800
```

并在知识库配置块中追加：

```bash
# 多格式解析限制
MAX_DOC_PAGES=100
MAX_DOC_CHARS=2000000
IMAGE_OCR_ENABLED=true
OCR_MODEL=qwen-vl-ocr
MAX_ZIP_UNCOMPRESSED=209715200
MAX_ZIP_ENTRIES=5000
```

- [ ] **Step 2: 修改 README**

在"知识库管理"一节中：

1. 把上传说明改为：

```markdown
3. 支持上传 `.md` / `.txt` / `.pdf`（文字版）/ `.docx` / `.pptx`；非 md 文档会先解析为规范化 Markdown 再入库
4. 页/幻灯片编号会保留在引用里；文档内图片会用 `qwen-vl-ocr` 提取文字（`IMAGE_OCR_ENABLED` 可关闭）
5. 可查看/编辑正文、删除覆盖版本、做检索预览（看 score 调 `RAG_TOP_K` / `RAG_SCORE_THRESHOLD`）
```

2. 在配置说明表格中追加：

```markdown
| `MAX_UPLOAD_BYTES` | 单次上传最大字节数，默认 50MB |
| `MAX_DOC_PAGES` | PDF 页数 / PPT 幻灯片数上限 |
| `MAX_DOC_CHARS` | 解析后正文最大字符数 |
| `IMAGE_OCR_ENABLED` / `OCR_MODEL` | 图片文字识别开关与模型 |
| `MAX_ZIP_UNCOMPRESSED` / `MAX_ZIP_ENTRIES` | DOCX/PPTX 解压限制（防 zip bomb） |
```

3. 增加说明：

```markdown
> 扫描版 PDF 暂不支持；`.doc/.ppt` 旧格式与 xlsx 暂不支持。
> 原始文件与图片保存在 `data/uploads/.raw/`、`data/uploads/.assets/`，删除文档时会一并清理。
```

- [ ] **Step 3: 回归**

Run: `uv run pytest -q` and `uv run ruff check .`
Expected: 全部通过，ruff 干净

- [ ] **Step 4: 提交**

```bash
git add .env.example README.md
git commit -m "docs: document multi-format ingestion"
```

---

## Task 13: 全量验证

- [ ] **Step 1: 静态检查与全量测试**

Run: `uv run ruff check .` and `uv run pytest -q`
Expected: ruff 干净；全部测试通过（预计 110+）

- [ ] **Step 2: 本地 mock 端到端（上传 → 列表 → 页标题 → 删除清理）**

```bash
uv run python -c "
from tests.docgen import make_docx, make_pdf, make_pptx
open('/tmp/smoke.docx','wb').write(make_docx())
open('/tmp/smoke.pptx','wb').write(make_pptx())
open('/tmp/smoke.pdf','wb').write(make_pdf())
"
TMP=$(mktemp -d)
MODEL_PROVIDER=mock MEMORY_BACKEND=memory ADMIN_TOKEN=dev-token \
  UPLOAD_DIR="$TMP/uploads" IMAGE_OCR_ENABLED=false \
  uv run uvicorn agentlab.main:app --host 127.0.0.1 --port 8092 >/tmp/kb-fmt-server.log 2>&1 &
PID=$!
trap 'kill $PID 2>/dev/null' EXIT
for i in $(seq 1 40); do curl -fsS http://127.0.0.1:8092/health >/dev/null 2>&1 && break; sleep 1; done

for f in docx pptx pdf; do
  code=$(curl -s -o /tmp/up.json -w "%{http_code}" -H "X-Admin-Token: dev-token" \
    -F "file=@/tmp/smoke.$f" http://127.0.0.1:8092/api/kb/docs)
  echo "$f -> $code $(cat /tmp/up.json)"
done

curl -s -H "X-Admin-Token: dev-token" http://127.0.0.1:8092/api/kb/docs > /tmp/doclist.json
uv run python -c "
import json
docs = json.load(open('/tmp/doclist.json'))['docs']
print('uploaded:', [d['doc_id'] for d in docs if d['doc_id'].startswith(('docx-','pptx-','pdf-'))])
"
DOC_ID=$(uv run python -c "import json; print([d['doc_id'] for d in json.load(open('/tmp/doclist.json'))['docs'] if d['doc_id'].startswith('docx-')][0])")
curl -s -X DELETE -H "X-Admin-Token: dev-token" "http://127.0.0.1:8092/api/kb/docs/$DOC_ID"; echo

echo "raw remaining:"; ls "$TMP/uploads/.raw" 2>/dev/null || echo "(none)"
echo "deleted doc assets:"; ls "$TMP/uploads/.assets/$DOC_ID" 2>/dev/null || echo "(none)"
grep -R "## 第\|## 幻灯片" "$TMP/uploads"/*.md | head -5
```

Expected:
- 三种格式均返回 201，`format` 分别为 docx/pptx/pdf
- 列表出现 `docx-`/`pptx-`/`pdf-` 前缀文档
- 删除 docx 文档后，`.raw` 中不再有该 doc_id，`.assets/<doc_id>` 不存在
- 规范化 md 中出现 `## 第 N 页`（PDF）与 `## 幻灯片 N`（PPTX）

- [ ] **Step 3: 提交**

若验证中修复了问题，按对应任务提交；无改动则无需提交。

---

## Self-Review Notes

- 规格覆盖：格式解析、规范化、页/幻灯片标题、表格、图片 OCR、doc_id、存储、限制、接口/页面、测试、文档均有对应 Task
- 类型一致：`ParsedDocument/Block/ParseError`、`assemble`、`parse_document`、`ImageOcr`、`Asset` 在 Task 2/7/8/9 中签名一致
- 无占位符：每个代码步骤均给出完整代码；Task 8 的 `__init__.py` 含一处显式修正说明，实现时直接采用顶部导入版本
