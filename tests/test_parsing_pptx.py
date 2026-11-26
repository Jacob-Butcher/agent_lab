import pytest

from agentlab.config import Settings
from agentlab.parsing.base import ParseError
from agentlab.parsing.pptx import parse_pptx
from tests.docgen import make_empty_pptx, make_pptx


def _settings(**overrides):
    return Settings(_env_file=None, **overrides)


def test_parse_pptx_slides_table_and_image():
    doc = parse_pptx("training.pptx", make_pptx(), _settings())
    pages = [block.text for block in doc.blocks if block.kind == "page"]
    assert pages == ["幻灯片 1"]
    assert any("退款 3 到 7" in block.text for block in doc.blocks)
    assert any(
        block.kind == "table" and "| 类型 | 时效 |" in block.text
        for block in doc.blocks
    )
    images = [block for block in doc.blocks if block.kind == "image"]
    assert images and images[0].image
    assert images[0].image_ext == "png"
    assert [block.kind for block in doc.blocks] == [
        "page",
        "text",
        "text",
        "table",
        "image",
    ]


def test_parse_pptx_rejects_page_limit():
    settings = _settings(max_doc_pages=1)
    with pytest.raises(ParseError) as exc:
        parse_pptx("training.pptx", make_pptx(slide_count=2), settings)
    assert exc.value.status == 413


def test_parse_pptx_multi_slide_pages():
    doc = parse_pptx("training.pptx", make_pptx(slide_count=2), _settings())
    pages = [block.text for block in doc.blocks if block.kind == "page"]
    assert pages == ["幻灯片 1", "幻灯片 2"]
    assert any("第 2 页内容" in block.text for block in doc.blocks)


def test_parse_pptx_prefers_core_title():
    doc = parse_pptx("x.pptx", make_pptx(title="培训手册"), _settings())
    assert doc.title == "培训手册"


def test_parse_pptx_rejects_empty_and_corrupt():
    with pytest.raises(ParseError) as empty:
        parse_pptx("empty.pptx", make_empty_pptx(), _settings())
    assert empty.value.status == 400
    with pytest.raises(ParseError) as corrupt:
        parse_pptx("bad.pptx", b"not a pptx", _settings())
    assert corrupt.value.status == 400


def test_parse_pptx_placeholder_picture():
    from tests.docgen import make_pptx_with_placeholder_picture

    doc = parse_pptx(
        "template.pptx", make_pptx_with_placeholder_picture(), _settings()
    )
    images = [block for block in doc.blocks if block.kind == "image"]
    assert images and images[0].image_ext == "png"


def test_parse_pptx_skips_blank_slide_but_keeps_numbering():
    from tests.docgen import make_pptx_with_blank_slide

    doc = parse_pptx("blank.pptx", make_pptx_with_blank_slide(), _settings())
    pages = [block.text for block in doc.blocks if block.kind == "page"]
    assert pages == ["幻灯片 2"]


def test_parse_pptx_title_falls_back_to_filename():
    doc = parse_pptx("training.pptx", make_pptx(), _settings())
    assert doc.title == "training"
