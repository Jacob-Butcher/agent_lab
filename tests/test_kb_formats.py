import pytest

from agentlab.config import Settings
from agentlab.kb import KbError, KBManager
from agentlab.llm import HashEmbeddings
from agentlab.rag.store import InMemoryChunkStore
from tests.docgen import make_docx, make_pptx


class FakeOcr:
    async def extract(self, image: bytes) -> str:
        return "截图文字：退货需保持完好"


def _manager(tmp_path, corpus_docs=None):
    settings = Settings(
        _env_file=None,
        model_provider="mock",
        memory_backend="memory",
        corpus_dir=str(tmp_path / "corpus"),
        upload_dir=str(tmp_path / "uploads"),
        max_upload_bytes=5 * 1024 * 1024,
    )
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for name, text in (corpus_docs or {}).items():
        (corpus / name).write_text(text, encoding="utf-8")
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


MD_POLICY = "---\ndoc_id: policy\ntitle: 政策\n---\n# 政策\n\n正文内容。\n"
BUILTIN = "---\ndoc_id: faq\ntitle: 内置\n---\n# 内置\n\n内置内容。\n"


async def test_upload_corrupt_document_returns_400(tmp_path):
    kb, _store = _manager(tmp_path)
    with pytest.raises(KbError) as exc:
        await kb.upload("bad.docx", b"not a docx")
    assert exc.value.status == 400


async def test_upload_txt_and_pdf_formats(tmp_path):
    from tests.docgen import make_pdf

    kb, _store = _manager(tmp_path)
    txt = await kb.upload("policy.txt", "售后政策".encode())
    assert txt["format"] == "txt"
    pdf = await kb.upload("refund.pdf", make_pdf())
    assert pdf["format"] == "pdf"


async def test_markdown_upload_clears_stale_source_files(tmp_path):
    kb, _store = _manager(tmp_path)
    await kb.upload("refund.docx", make_docx(), doc_id="policy")
    assert list((kb.upload_dir / ".raw").glob("policy.*"))
    assert (kb.upload_dir / ".assets" / "policy").exists()

    again = await kb.upload("policy.md", MD_POLICY.encode(), overwrite=True)

    assert again["format"] == "md"
    assert not list((kb.upload_dir / ".raw").glob("policy.*"))
    assert not (kb.upload_dir / ".assets" / "policy").exists()


async def test_delete_override_reverts_and_cleans_sources(tmp_path):
    from agentlab.rag.ingest import ingest_corpus_dirs

    kb, store = _manager(tmp_path, {"builtin.md": BUILTIN})
    await ingest_corpus_dirs([kb.corpus_dir, kb.upload_dir], store, kb.embeddings)
    await kb.upload("refund.docx", make_docx(), doc_id="faq", overwrite=True)

    result = await kb.delete("faq")

    assert result["result"] == "reverted_to_builtin"
    assert not list((kb.upload_dir / ".raw").glob("faq.*"))
    assert not (kb.upload_dir / ".assets" / "faq").exists()


async def test_dotted_doc_id_cleanup_does_not_touch_neighbors(tmp_path):
    kb, _store = _manager(tmp_path)
    await kb.upload("a.docx", make_docx(), doc_id="v1.2")
    await kb.upload("b.docx", make_docx(), doc_id="v1.2.extra")

    await kb.delete("v1.2")

    remaining = sorted(path.name for path in (kb.upload_dir / ".raw").iterdir())
    assert remaining == ["v1.2.extra.docx"]
