from pathlib import Path

from agentlab.llm import HashEmbeddings
from agentlab.rag.ingest import ingest_corpus, ingest_corpus_dirs
from agentlab.rag.store import InMemoryChunkStore

DOC = """---
doc_id: refund
title: 退款时效
---
# 退款时效

退款一般 3 到 7 个工作日到账。

## 关键规则

- 银行卡 3 到 7 个工作日。
"""


async def test_ingest_adds_then_skips(tmp_path: Path):
    (tmp_path / "refund.md").write_text(DOC, encoding="utf-8")
    store = InMemoryChunkStore()
    embeddings = HashEmbeddings(64)

    first = await ingest_corpus(tmp_path, store, embeddings)
    assert first.added == 1
    assert first.skipped == 0
    assert first.chunks >= 1

    second = await ingest_corpus(tmp_path, store, embeddings)
    assert second.added == 0
    assert second.skipped == 1


async def test_changed_doc_is_replaced(tmp_path: Path):
    path = tmp_path / "refund.md"
    path.write_text(DOC, encoding="utf-8")
    store = InMemoryChunkStore()
    embeddings = HashEmbeddings(64)
    await ingest_corpus(tmp_path, store, embeddings)

    path.write_text(DOC.replace("3 到 7", "1 到 3"), encoding="utf-8")
    stats = await ingest_corpus(tmp_path, store, embeddings)
    assert stats.changed == 1
    rows = await store.search(await embeddings.aembed_query("退款"), k=5, threshold=0.0)
    assert any("1 到 3" in row.content for row in rows)


async def test_removed_doc_is_deleted(tmp_path: Path):
    path = tmp_path / "refund.md"
    path.write_text(DOC, encoding="utf-8")
    store = InMemoryChunkStore()
    embeddings = HashEmbeddings(64)
    await ingest_corpus(tmp_path, store, embeddings)

    path.unlink()
    stats = await ingest_corpus(tmp_path, store, embeddings)
    assert stats.deleted == 1
    assert await store.get_doc_hashes() == {}


async def test_ingest_corpus_dirs_later_overrides(tmp_path):
    corpus = tmp_path / "corpus"
    uploads = tmp_path / "uploads"
    corpus.mkdir()
    uploads.mkdir()
    (corpus / "a.md").write_text(DOC, encoding="utf-8")
    (uploads / "a.md").write_text(DOC.replace("3 到 7", "1 到 3"), encoding="utf-8")
    store = InMemoryChunkStore()
    embeddings = HashEmbeddings(64)

    stats = await ingest_corpus_dirs([corpus, uploads], store, embeddings)

    assert stats.added == 1
    rows = await store.search(await embeddings.aembed_query("退款"), k=5, threshold=0.0)
    assert any("1 到 3" in row.content for row in rows)


async def test_ingest_corpus_dirs_deletes_removed(tmp_path):
    corpus = tmp_path / "corpus"
    uploads = tmp_path / "uploads"
    corpus.mkdir()
    uploads.mkdir()
    (uploads / "a.md").write_text(DOC, encoding="utf-8")
    store = InMemoryChunkStore()
    embeddings = HashEmbeddings(64)
    await ingest_corpus_dirs([corpus, uploads], store, embeddings)

    (uploads / "a.md").unlink()
    stats = await ingest_corpus_dirs([corpus, uploads], store, embeddings)

    assert stats.deleted == 1
    assert await store.get_doc_hashes() == {}
