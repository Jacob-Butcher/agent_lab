from agentlab.llm import HashEmbeddings
from agentlab.models import Chunk
from agentlab.rag.retriever import retrieve
from agentlab.rag.store import InMemoryChunkStore


async def _store_with_doc():
    store = InMemoryChunkStore()
    embeddings = HashEmbeddings(64)
    chunk = Chunk("refund", 0, "退款时效", "关键规则", "退款一般 3 到 7 个工作日到账。")
    await store.replace_doc(
        "refund", "h1", [chunk], [await embeddings.aembed_query(chunk.content)]
    )
    return store, embeddings


async def test_retrieve_builds_citations_and_context():
    store, embeddings = await _store_with_doc()
    result = await retrieve("退款多久到账", embeddings, store, top_k=5, threshold=0.0)
    assert result.chunks
    assert result.citations[0]["doc_id"] == "refund"
    assert "[refund#0]" in result.context
    assert "退款时效" in result.context


async def test_retrieve_empty_when_below_threshold():
    store, embeddings = await _store_with_doc()
    result = await retrieve(
        "完全无关的问题", embeddings, store, top_k=5, threshold=0.99
    )
    assert result.chunks == []
    assert result.context == ""
    assert result.citations == []
