import io
import zipfile

import pytest

from agentlab.config import Settings
from agentlab.parsing.base import (
    ParseError,
    clean_text,
    detect_format,
    sha256_bytes,
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


def test_detect_format_rejects_zip_bomb():
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


def test_clean_text_collapses_whitespace_only_lines():
    assert clean_text("a\n \n \n \nb") == "a\n\nb"
    assert clean_text("a\n\x0c\n\x0c\nb") == "a\n\nb"


def test_table_to_markdown_trims_cells_and_drops_empty_rows():
    md = table_to_markdown([["h1", "h2"], ["\n", "  "], ["\nfoo\n", "bar\n"]])
    assert "| h1 | h2 |" in md
    assert "| foo | bar |" in md
    assert "<br>" not in md
    assert md.count("| --- | --- |") == 1


def test_parse_error_argument_order():
    exc = ParseError("boom", 413)
    assert exc.detail == "boom"
    assert exc.status == 413


def test_detect_format_accepts_txt_pptx_pdf():
    from tests.docgen import make_pdf, make_pptx

    assert detect_format("a.txt", "售后".encode(), _settings()) == "txt"
    assert detect_format("a.pptx", make_pptx(), _settings()) == "pptx"
    assert detect_format("a.pdf", make_pdf(), _settings()) == "pdf"


def test_detect_format_rejects_docx_as_pptx():
    from tests.docgen import make_docx

    with pytest.raises(ParseError):
        detect_format("a.pptx", make_docx(), _settings())


def test_detect_format_rejects_entry_count_limit():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for index in range(3):
            archive.writestr(f"word/f{index}.xml", "x")
    settings = _settings(max_zip_entries=2)
    with pytest.raises(ParseError) as exc:
        detect_format("a.docx", buffer.getvalue(), settings)
    assert exc.value.status == 413


def test_detect_format_rejects_bad_zip():
    with pytest.raises(ParseError) as exc:
        detect_format("a.docx", b"not a zip", _settings())
    assert exc.value.status == 400


def test_sha256_bytes_known_value():
    assert sha256_bytes(b"abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
