import asyncio

import pytest

from agentlab.config import Settings
from agentlab.parsing import assemble as assemble_module
from agentlab.parsing.assemble import assemble
from agentlab.parsing.base import Block, ParsedDocument, ParseError
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


class SlowOcr:
    async def extract(self, image: bytes) -> str:
        await asyncio.sleep(0.05)
        return "慢"


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
    assert len(result.assets) == 1


async def test_assemble_rejects_empty_and_too_large():
    with pytest.raises(ParseError):
        await assemble(
            ParsedDocument("t", [Block("text", text="   ")]), None, _settings()
        )
    with pytest.raises(ParseError) as exc:
        await assemble(
            ParsedDocument("t", [Block("text", text="x" * 20)]),
            None,
            _settings(max_doc_chars=10),
        )
    assert exc.value.status == 413


async def test_assemble_caps_images_per_doc(monkeypatch):
    monkeypatch.setattr(assemble_module, "MAX_IMAGES_PER_DOC", 1)
    document = ParsedDocument(
        "t",
        [
            Block("image", image=png_bytes(200, 100, (200, 0, 0)), image_ext="png"),
            Block("image", image=png_bytes(200, 100, (0, 200, 0)), image_ext="png"),
        ],
    )
    ocr = FakeOcr()
    result = await assemble(document, ocr, _settings())
    assert len(result.assets) == 1
    assert ocr.calls == 1


async def test_assemble_table_and_multiline_ocr_quoted():
    document = ParsedDocument(
        "t",
        [
            Block("table", text="| a | b |"),
            Block("image", image=png_bytes(200, 100, (1, 2, 3))),
        ],
    )
    result = await assemble(document, FakeOcr("第一行\n第二行"), _settings())
    assert "| a | b |" in result.markdown
    assert "> 图片文字：第一行\n> 第二行" in result.markdown


async def test_assemble_two_images_named_in_order():
    document = ParsedDocument(
        "t",
        [
            Block("text", text="正文"),
            Block("image", image=png_bytes(200, 100, (10, 0, 0))),
            Block("image", image=png_bytes(200, 100, (0, 10, 0))),
        ],
    )
    result = await assemble(document, None, _settings())
    assert [asset.name for asset in result.assets] == [
        "image-01.png",
        "image-02.png",
    ]


async def test_assemble_ocr_budget_times_out(monkeypatch):
    monkeypatch.setattr(assemble_module, "OCR_BUDGET_SECONDS", 0.01)
    document = ParsedDocument(
        "t",
        [Block("text", text="正文"), Block("image", image=png_bytes(200, 100))],
    )
    result = await assemble(document, SlowOcr(), _settings())
    assert "正文" in result.markdown
    assert "图片文字" not in result.markdown
    assert len(result.assets) == 1


def test_parse_document_dispatch():
    from agentlab.parsing import parse_document

    kind, parsed = parse_document("a.docx", make_docx(), _settings())
    assert kind == "docx"
    assert parsed.title
