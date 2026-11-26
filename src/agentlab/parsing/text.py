import logging
from pathlib import Path

from charset_normalizer import from_bytes

from agentlab.config import Settings
from agentlab.parsing.base import Block, ParsedDocument, ParseError, clean_text

logger = logging.getLogger(__name__)


def _decode_text(data: bytes) -> str:
    """UTF-8 first; Chinese GBK is often misdetected as cp949, so fall back to
    gb18030 for that case only.

    Tradeoff: genuine cp949/euc-kr documents will be decoded as GB18030
    (mojibake). This is an intentional Chinese-first decision.
    """
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    best = from_bytes(data).best()
    if best is not None and best.encoding.lower() in {"cp949", "euc_kr", "uhc"}:
        logger.warning(
            "text decode: detector picked %s, falling back to gb18030",
            best.encoding,
        )
        try:
            return data.decode("gb18030")
        except UnicodeDecodeError:
            pass
    if best is not None:
        return str(best)
    logger.warning("text decode: no encoding detected, using replacement decode")
    try:
        return data.decode("gb18030")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")


def parse_txt(filename: str, data: bytes, settings: Settings) -> ParsedDocument:
    """Parse a plain-text file into one text block (size limits checked in assemble)."""
    if b"\x00" in data:
        raise ParseError("不是有效的文本文件")
    text = _decode_text(data)
    body = clean_text(text)
    if not body:
        raise ParseError("文本内容为空")
    return ParsedDocument(
        title=Path(filename).stem,
        blocks=[Block("text", text=body)],
    )
