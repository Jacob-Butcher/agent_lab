"""Document parsers for multi-format knowledge-base ingestion."""

from agentlab.config import Settings
from agentlab.parsing.base import ParsedDocument, ParseError, detect_format
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
