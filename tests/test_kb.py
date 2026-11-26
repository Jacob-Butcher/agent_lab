import frontmatter
import pytest

from agentlab.config import Settings
from agentlab.kb import KbError, KBManager
from agentlab.llm import HashEmbeddings
from agentlab.rag.ingest import ingest_corpus_dirs
from agentlab.rag.store import InMemoryChunkStore

BODY = "# 常见问题\n\n## 退款\n\n退款 3 到 7 个工作日到账。\n"
DOC = "---\ndoc_id: faq\ntitle: 常见问题\n---\n" + BODY
OTHER = "---\ndoc_id: other\ntitle: 其他\n---\n# 其他\n\n其他内容。\n"
TAGGED = "---\ndoc_id: faq\ntitle: 常见问题\ntags:\n  - a\n  - b\n---\n" + BODY


class ToggleEmbeddings(HashEmbeddings):
    def __init__(self, dim: int = 64) -> None:
        super().__init__(dim)
        self.fail = False

    async def aembed_documents(self, texts):
        if self.fail:
            raise RuntimeError("boom")
        return await super().aembed_documents(texts)

    async def aembed_query(self, text):
        if self.fail:
            raise RuntimeError("boom")
        return await super().aembed_query(text)


def _manager(tmp_path, corpus_docs=None, embeddings=None):
    corpus = tmp_path / "corpus"
    uploads = tmp_path / "uploads"
    corpus.mkdir()
    uploads.mkdir()
    for name, text in (corpus_docs or {}).items():
        (corpus / name).write_text(text, encoding="utf-8")
    settings = Settings(
        _env_file=None,
        model_provider="mock",
        memory_backend="memory",
        corpus_dir=str(corpus),
        upload_dir=str(uploads),
        max_upload_bytes=1024,
    )
    store = InMemoryChunkStore()
    embeddings = embeddings or HashEmbeddings(64)
    return KBManager(settings, store, embeddings), store, corpus, uploads


async def test_upload_indexes_and_lists(tmp_path):
    kb, _store, _corpus, uploads = _manager(tmp_path)

    result = await kb.upload("faq.md", DOC.encode("utf-8"))

    assert result == {
        "doc_id": "faq",
        "title": "常见问题",
        "chunks": result["chunks"],
        "source": "uploads",
    }
    assert result["chunks"] >= 1
    assert (uploads / "faq.md").exists()
    docs = await kb.list_docs()
    assert docs[0]["doc_id"] == "faq"
    assert docs[0]["source"] == "uploads"
    assert docs[0]["chunks"] == result["chunks"]


async def test_duplicate_requires_overwrite(tmp_path):
    kb, *_ = _manager(tmp_path)
    await kb.upload("faq.md", DOC.encode("utf-8"))

    with pytest.raises(KbError) as exc:
        await kb.upload("faq.md", DOC.encode("utf-8"))
    assert exc.value.status == 409

    result = await kb.upload(
        "faq.md", DOC.replace("3 到 7", "1 到 3").encode("utf-8"), overwrite=True
    )
    assert result["doc_id"] == "faq"


async def test_upload_overrides_builtin_source(tmp_path):
    kb, store, corpus, _uploads = _manager(tmp_path, {"builtin.md": DOC})
    await ingest_corpus_dirs([corpus, kb.upload_dir], store, kb.embeddings)

    result = await kb.upload(
        "faq.md", DOC.replace("3 到 7", "1 到 3").encode("utf-8"), overwrite=True
    )

    assert result["source"] == "uploads"
    docs = await kb.list_docs()
    assert docs[0]["source"] == "uploads"


async def test_edit_builtin_creates_override_and_reverts(tmp_path):
    kb, store, corpus, uploads = _manager(tmp_path, {"builtin.md": DOC})
    await ingest_corpus_dirs([corpus, kb.upload_dir], store, kb.embeddings)

    result = await kb.save_body("faq", BODY.replace("3 到 7", "1 到 3"))
    assert result == {"doc_id": "faq", "chunks": result["chunks"], "source": "uploads"}
    assert (uploads / "faq.md").exists()
    doc = await kb.get_doc("faq")
    assert doc["source"] == "uploads"
    assert "1 到 3" in doc["body"]
    assert "frontmatter" not in doc["body"]

    deleted = await kb.delete("faq")
    assert deleted == {"doc_id": "faq", "result": "reverted_to_builtin"}
    doc = await kb.get_doc("faq")
    assert doc["source"] == "corpus"
    rows = await store.search(await kb.embeddings.aembed_query("退款"), k=5, threshold=0.0)
    assert any("3 到 7" in row.content for row in rows)


async def test_delete_upload_without_builtin(tmp_path):
    kb, _store, _corpus, _uploads = _manager(tmp_path)
    await kb.upload("faq.md", DOC.encode("utf-8"))

    deleted = await kb.delete("faq")

    assert deleted == {"doc_id": "faq", "result": "deleted_override"}
    with pytest.raises(KbError) as exc:
        await kb.get_doc("faq")
    assert exc.value.status == 404


async def test_delete_builtin_forbidden(tmp_path):
    kb, *_ = _manager(tmp_path, {"builtin.md": DOC})

    with pytest.raises(KbError) as exc:
        await kb.delete("faq")
    assert exc.value.status == 403


async def test_invalid_doc_id_rejected(tmp_path):
    kb, *_ = _manager(tmp_path)
    bad = DOC.replace("doc_id: faq", "doc_id: ../evil")

    with pytest.raises(KbError) as exc:
        await kb.upload("evil.md", bad.encode("utf-8"))
    assert exc.value.status == 400


async def test_oversized_upload_rejected(tmp_path):
    kb, *_ = _manager(tmp_path)

    with pytest.raises(KbError) as exc:
        await kb.upload("big.md", b"x" * 2048)
    assert exc.value.status == 413


async def test_empty_body_rejected(tmp_path):
    kb, *_ = _manager(tmp_path)

    with pytest.raises(KbError) as exc:
        await kb.upload("empty.md", b"---\ndoc_id: empty\n---\n")
    assert exc.value.status == 400


async def test_malformed_frontmatter_rejected(tmp_path):
    kb, *_ = _manager(tmp_path)
    bad = b"---\ndoc_id: [unclosed\n---\n# x\n\ncontent\n"

    with pytest.raises(KbError) as exc:
        await kb.upload("bad.md", bad)
    assert exc.value.status == 400


async def test_delete_override_keeps_other_docs(tmp_path):
    kb, store, corpus, _uploads = _manager(tmp_path, {"builtin.md": DOC, "other.md": OTHER})
    await ingest_corpus_dirs([corpus, kb.upload_dir], store, kb.embeddings)
    await kb.upload("faq.md", DOC.replace("3 到 7", "1 到 3").encode("utf-8"), overwrite=True)

    await kb.delete("faq")

    assert set(await store.get_doc_hashes()) == {"faq", "other"}


async def test_revert_failure_keeps_file_and_returns_502(tmp_path):
    embeddings = ToggleEmbeddings()
    kb, store, corpus, uploads = _manager(
        tmp_path, {"builtin.md": DOC}, embeddings=embeddings
    )
    await ingest_corpus_dirs([corpus, kb.upload_dir], store, kb.embeddings)
    await kb.upload("faq.md", DOC.replace("3 到 7", "1 到 3").encode("utf-8"), overwrite=True)

    embeddings.fail = True
    with pytest.raises(KbError) as exc:
        await kb.delete("faq")
    assert exc.value.status == 502
    assert (uploads / "faq.md").exists()


async def test_overwrite_removes_stale_upload_file(tmp_path):
    kb, _store, _corpus, uploads = _manager(tmp_path)
    (uploads / "legacy.md").write_text(DOC, encoding="utf-8")

    await kb.upload("faq.md", DOC.replace("3 到 7", "1 到 3").encode("utf-8"), overwrite=True)

    assert not (uploads / "legacy.md").exists()
    assert (uploads / "faq.md").exists()
    assert len(await kb.list_docs()) == 1


async def test_save_body_rejects_invalid_doc_id(tmp_path):
    kb, *_ = _manager(tmp_path, {"builtin.md": DOC})
    with pytest.raises(KbError) as exc:
        await kb.save_body("../evil", BODY)
    assert exc.value.status == 400


async def test_save_body_empty_and_unknown(tmp_path):
    kb, *_ = _manager(tmp_path, {"builtin.md": DOC})
    with pytest.raises(KbError) as exc:
        await kb.save_body("faq", "   ")
    assert exc.value.status == 400
    with pytest.raises(KbError) as exc:
        await kb.save_body("missing", BODY)
    assert exc.value.status == 404


async def test_failed_upload_embedding_keeps_stale_file(tmp_path):
    embeddings = ToggleEmbeddings()
    kb, _store, _corpus, uploads = _manager(tmp_path, embeddings=embeddings)
    (uploads / "legacy.md").write_text(DOC, encoding="utf-8")
    embeddings.fail = True

    with pytest.raises(KbError) as exc:
        await kb.upload(
            "faq.md", DOC.replace("3 到 7", "1 到 3").encode("utf-8"), overwrite=True
        )

    assert exc.value.status == 502
    assert (uploads / "legacy.md").exists()


async def test_malformed_file_in_dir_raises_kb_error(tmp_path):
    kb, *_ = _manager(tmp_path)
    (kb.upload_dir / "bad.md").write_text("---\n: [\n---\n# x\n", encoding="utf-8")

    with pytest.raises(KbError) as exc:
        await kb.list_docs()
    assert exc.value.status == 500


async def test_save_body_preserves_metadata(tmp_path):
    kb, _store, _corpus, uploads = _manager(tmp_path, {"builtin.md": TAGGED})

    await kb.save_body("faq", BODY.replace("3 到 7", "1 到 3"))

    post = frontmatter.load(uploads / "faq.md")
    assert post.metadata["tags"] == ["a", "b"]
    assert post.metadata["doc_id"] == "faq"


LONG_TEXT = "退款规则说明。" * 40
LONG_DOC = f"---\ndoc_id: long\ntitle: 长文档\n---\n# 长文档\n\n{LONG_TEXT}\n"


async def test_search_clamps_params(tmp_path):
    kb, store, corpus, _uploads = _manager(tmp_path, {"builtin.md": DOC})
    await ingest_corpus_dirs([corpus, kb.upload_dir], store, kb.embeddings)

    result = await kb.search("退款", top_k=999, threshold=2)

    assert result["effective"] == {"top_k": 20, "threshold": 1.0}


async def test_search_returns_truncated_previews_ordered(tmp_path):
    kb, store, corpus, _uploads = _manager(tmp_path, {"long.md": LONG_DOC})
    await ingest_corpus_dirs([corpus, kb.upload_dir], store, kb.embeddings)

    result = await kb.search("退款", top_k=5, threshold=0.0)

    assert result["effective"] == {"top_k": 5, "threshold": 0.0}
    assert result["results"]
    row = result["results"][0]
    assert len(row["content"]) == 200
    assert row["doc_id"] == "long"
    scores = [item["score"] for item in result["results"]]
    assert scores == sorted(scores, reverse=True)


async def test_search_failure_returns_502(tmp_path):
    embeddings = ToggleEmbeddings()
    kb, store, corpus, _uploads = _manager(
        tmp_path, {"builtin.md": DOC}, embeddings=embeddings
    )
    await ingest_corpus_dirs([corpus, kb.upload_dir], store, kb.embeddings)

    embeddings.fail = True
    with pytest.raises(KbError) as exc:
        await kb.search("退款")
    assert exc.value.status == 502


async def test_search_rejects_empty_query(tmp_path):
    kb, *_ = _manager(tmp_path)

    with pytest.raises(KbError) as exc:
        await kb.search("   ")
    assert exc.value.status == 400
