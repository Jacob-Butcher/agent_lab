import pytest

from agentlab.config import Settings
from agentlab.parsing.base import ParseError
from agentlab.parsing.text import parse_txt


def _settings():
    return Settings(_env_file=None)


def test_parse_txt_utf8():
    doc = parse_txt("退款.txt", "第一段。\n\n第二段。".encode(), _settings())
    assert doc.title == "退款"
    assert doc.blocks[0].kind == "text"
    assert "第二段" in doc.blocks[0].text


def test_parse_txt_gbk():
    doc = parse_txt("政策.txt", "售后政策".encode("gbk"), _settings())
    assert "售后政策" in doc.blocks[0].text


def test_parse_txt_rejects_empty_and_binary():
    with pytest.raises(ParseError) as empty:
        parse_txt("empty.txt", b"   ", _settings())
    assert empty.value.status == 400
    with pytest.raises(ParseError) as binary:
        parse_txt("bin.txt", b"a\x00b", _settings())
    assert binary.value.status == 400


def test_parse_txt_longer_gbk():
    doc = parse_txt("policy.txt", "退款政策说明".encode("gbk"), _settings())
    assert "退款政策" in doc.blocks[0].text


def test_parse_txt_does_not_override_big5_detection():
    # Big5 is out of scope, but a confident big5 detection must not be
    # overridden by the GBK fallback.
    doc = parse_txt("traditional.txt", "繁體中文".encode("big5"), _settings())
    assert "繁體中文" in doc.blocks[0].text


def test_parse_txt_strips_utf8_bom():
    doc = parse_txt("bom.txt", b"\xef\xbb\xbf" + "退款".encode(), _settings())
    assert not doc.blocks[0].text.startswith("\ufeff")
    assert doc.blocks[0].text.startswith("退款")
