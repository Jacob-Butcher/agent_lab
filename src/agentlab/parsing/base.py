import hashlib
import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import filetype

from agentlab.config import Settings

FORMAT_EXTENSIONS = {
    ".txt": "txt",
    ".pdf": "pdf",
    ".docx": "docx",
    ".pptx": "pptx",
}


class ParseError(Exception):
    """Parsing failure; argument order is (detail, status).

    Note: this intentionally differs from KbError(status, detail); the
    KBManager translation must use KbError(exc.status, exc.detail).
    """

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
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = "".join(
        ch if ch in "\n\t" else (" " if ord(ch) < 32 else ch) for ch in text
    )
    cleaned = "\n".join(line.rstrip() for line in cleaned.split("\n"))
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def table_to_markdown(rows: list[list[str | None]]) -> str:
    cleaned: list[list[str]] = []
    for row in rows:
        cells = []
        for cell in row:
            raw = ("" if cell is None else str(cell)).strip()
            cells.append(
                raw.replace("\\", "\\\\")
                .replace("|", "\\|")
                .replace("\n", "<br>")
            )
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
    try:
        infos = archive.infolist()
        if len(infos) > settings.max_zip_entries:
            raise ParseError("文档解压条目过多，已拒绝", 413)
        if sum(info.file_size for info in infos) > settings.max_zip_uncompressed:
            raise ParseError("文档解压后体积过大，已拒绝", 413)
    except ParseError:
        archive.close()
        raise
    return archive


def detect_format(filename: str, data: bytes, settings: Settings) -> str:
    kind = FORMAT_EXTENSIONS.get(Path(filename).suffix.lower())
    if kind is None:
        raise ParseError(
            "不支持的文件类型，仅支持 .txt/.pdf/.docx/.pptx（Markdown 走原有上传流程）"
        )
    guessed = filetype.guess(data)
    if kind == "pdf":
        if not (
            (guessed is not None and guessed.extension == "pdf")
            or b"%PDF-" in data[:1024]
        ):
            raise ParseError("文件内容与扩展名不符")
    elif kind in {"docx", "pptx"}:
        with _open_zip(data, settings) as archive:
            prefix = "word/" if kind == "docx" else "ppt/"
            if not any(name.startswith(prefix) for name in archive.namelist()):
                raise ParseError("文件内容与扩展名不符")
    return kind
