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


def test_parse_pdf_rejects_image_only():
    from tests.docgen import make_image_only_pdf

    with pytest.raises(ParseError) as exc:
        parse_pdf("scan.pdf", make_image_only_pdf(), _settings())
    assert exc.value.status == 400
    assert "扫描件" in exc.value.detail


def test_parse_pdf_does_not_duplicate_table_text():
    doc = parse_pdf("refund.pdf", make_pdf(), _settings())
    texts = [block.text for block in doc.blocks if block.kind == "text"]
    assert all("No reason" not in text for text in texts)
    assert any(
        "No reason" in block.text for block in doc.blocks if block.kind == "table"
    )


def test_parse_pdf_uses_metadata_title():
    doc = parse_pdf("file.pdf", make_pdf(title="Refund Policy 2026"), _settings())
    assert doc.title == "Refund Policy 2026"
