from pathlib import Path

from agentlab.config import Settings
from agentlab.graph.build import build_graph
from agentlab.graph.nodes import make_nodes
from agentlab.llm import HashEmbeddings, MockChatModel
from agentlab.memory import InMemorySessionMemory
from agentlab.rag.ingest import ingest_corpus
from agentlab.rag.store import InMemoryChunkStore


async def _graph(tmp_path: Path):
    (tmp_path / "refund.md").write_text(
        """---
doc_id: refund
title: 退款时效
---
# 退款时效

退款一般 3 到 7 个工作日到账。

## 关键规则

- 银行卡 3 到 7 个工作日。
""",
        encoding="utf-8",
    )
    settings = Settings(_env_file=None, model_provider="mock", memory_backend="memory")
    embeddings = HashEmbeddings(64)
    store = InMemoryChunkStore()
    await ingest_corpus(tmp_path, store, embeddings)
    memory = InMemorySessionMemory(max_messages=settings.max_history_messages)
    nodes = make_nodes(MockChatModel(), embeddings, store, memory, settings)
    return build_graph(nodes), memory, settings, embeddings, store


async def test_graph_answers_and_writes_memory(tmp_path: Path):
    graph, memory, _, _, _ = await _graph(tmp_path)
    result = await graph.ainvoke(
        {"query": "退款多久到账", "session_id": "session-1234"}
    )
    assert result["answer"]
    assert result["citations"]
    messages = await memory.load("session-1234", 10)
    assert [m.role for m in messages] == ["user", "assistant"]


async def test_graph_streams_tokens(tmp_path: Path):
    graph, _, _, _, _ = await _graph(tmp_path)
    tokens: list[str] = []
    async for mode, payload in graph.astream(
        {"query": "退款多久到账", "session_id": "session-1234"},
        stream_mode=["messages", "updates"],
    ):
        if mode == "messages":
            chunk, metadata = payload
            if metadata.get("langgraph_node") == "respond" and chunk.content:
                tokens.append(str(chunk.content))
    assert tokens
    assert "模拟回答" in "".join(tokens)


async def test_normalize_loads_history(tmp_path: Path):
    _, memory, settings, embeddings, store = await _graph(tmp_path)
    await memory.append("session-1234", "上一轮问题", "上一轮回答")
    nodes = make_nodes(
        MockChatModel(),
        embeddings,
        store,
        memory,
        settings,
    )
    state = await nodes.normalize({"query": "新问题", "session_id": "session-1234"})
    assert state["history"][-1]["content"] == "上一轮回答"
