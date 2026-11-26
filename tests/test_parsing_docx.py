import pytest

from agentlab.config import Settings
from agentlab.parsing.base import ParseError
from agentlab.parsing.docx import parse_docx
from tests.docgen import make_docx, make_empty_docx


def _settings():
    return Settings(_env_file=None)


def test_parse_docx_heading_paragraph_table_and_image():
    doc = parse_docx("refund.docx", make_docx(), _settings())
    texts = [block.text for block in doc.blocks if block.kind == "text"]
    assert any(text.startswith("# 退款政策") for text in texts)
    assert any("7 天内" in text for text in texts)
    assert "- 列表项" in texts
    assert any(
        block.kind == "table" and "| 类型 | 时效 |" in block.text
        for block in doc.blocks
    )
    images = [block for block in doc.blocks if block.kind == "image"]
    assert images and images[0].image
    assert images[0].image_ext == "png"
    assert [block.kind for block in doc.blocks] == [
        "text",
        "text",
        "text",
        "table",
        "image",
    ]


def test_parse_docx_title_falls_back_to_filename():
    doc = parse_docx("售后手册.docx", make_docx(), _settings())
    assert doc.title == "售后手册"


def test_parse_docx_prefers_core_title():
    doc = parse_docx("x.docx", make_docx(title="我的标题"), _settings())
    assert doc.title == "我的标题"


def test_parse_docx_rejects_empty_and_corrupt():
    with pytest.raises(ParseError) as empty:
        parse_docx("empty.docx", make_empty_docx(), _settings())
    assert empty.value.status == 400
    with pytest.raises(ParseError) as corrupt:
        parse_docx("bad.docx", b"not a docx", _settings())
    assert corrupt.value.status == 400
