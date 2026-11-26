import pytest

from agentlab.models import Chunk
from agentlab.rag.store import InMemoryChunkStore, parse_vector_dim


def _chunk(doc_id="d1", index=0, content="退款一般 3 到 7 个工作日到账"):
    return Chunk(doc_id, index, "退款时效", "关键规则", content)


async def test_replace_and_search():
    store = InMemoryChunkStore()
    await store.replace_doc("d1", "hash1", [_chunk()], [[1.0, 0.0]])
    rows = await store.search([1.0, 0.0], k=5, threshold=0.0)
    assert len(rows) == 1
    assert rows[0].doc_id == "d1"
    assert rows[0].score == pytest.approx(1.0)
    assert rows[0].to_citation()["doc_id"] == "d1"


async def test_replace_removes_old_chunks():
    store = InMemoryChunkStore()
    await store.replace_doc(
        "d1", "hash1", [_chunk(index=0), _chunk(index=1)], [[1.0], [1.0]]
    )
    await store.replace_doc("d1", "hash2", [_chunk(index=0, content="新内容")], [[1.0]])
    rows = await store.search([1.0], k=10, threshold=0.0)
    assert len(rows) == 1
    assert "新内容" in rows[0].content


async def test_threshold_and_top_k():
    store = InMemoryChunkStore()
    await store.replace_doc("d1", "h1", [_chunk("d1", 0)], [[1.0, 0.0]])
    await store.replace_doc("d2", "h2", [_chunk("d2", 0)], [[0.0, 1.0]])
    assert await store.search([0.5, 0.5], k=5, threshold=0.9) == []
    rows = await store.search([1.0, 0.0], k=1, threshold=0.0)
    assert len(rows) == 1 and rows[0].doc_id == "d1"


async def test_delete_doc_clears_hash():
    store = InMemoryChunkStore()
    await store.replace_doc("d1", "h1", [_chunk()], [[1.0]])
    assert (await store.get_doc_hashes()) == {"d1": "h1"}
    await store.delete_doc("d1")
    assert (await store.get_doc_hashes()) == {}
    assert await store.search([1.0], k=5, threshold=0.0) == []


def test_parse_vector_dim():
    assert parse_vector_dim("vector(1024)") == 1024
    assert parse_vector_dim("vector(64)") == 64
    with pytest.raises(ValueError):
        parse_vector_dim("text")


async def test_list_docs():
    store = InMemoryChunkStore()
    assert await store.list_docs() == []

    await store.replace_doc(
        "d2", "h2", [Chunk("d2", 0, "发票规则", "关键规则", "发票内容")], [[1.0]]
    )
    await store.replace_doc(
        "d1", "h1", [_chunk("d1", 0), _chunk("d1", 1)], [[1.0], [1.0]]
    )

    docs = await store.list_docs()
    assert [(d.doc_id, d.title, d.chunks) for d in docs] == [
        ("d1", "退款时效", 2),
        ("d2", "发票规则", 1),
    ]
