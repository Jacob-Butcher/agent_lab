import math

import pytest
from langchain_core.messages import HumanMessage

from agentlab.config import Settings
from agentlab.llm import HashEmbeddings, MockChatModel, build_chat_model, build_embeddings


def test_hash_embeddings_are_deterministic_and_normalized():
    emb = HashEmbeddings(dim=64)
    v1 = emb.embed_query("退款多久到账")
    v2 = emb.embed_query("退款多久到账")
    assert v1 == v2
    assert len(v1) == 64
    assert math.isclose(sum(x * x for x in v1), 1.0, rel_tol=1e-6)


def test_hash_embeddings_distinguish_text():
    emb = HashEmbeddings(dim=256)
    assert emb.embed_query("退款") != emb.embed_query("发票")


async def test_mock_chat_streams_text():
    model = MockChatModel()
    chunks = [c async for c in model.astream([HumanMessage(content="退款多久到账")])]
    text = "".join(str(c.content) for c in chunks)
    assert "模拟回答" in text
    assert "退款多久到账" in text


def test_factory_returns_mock_models():
    settings = Settings(_env_file=None, model_provider="mock", embedding_dim=32)
    assert isinstance(build_chat_model(settings), MockChatModel)
    assert isinstance(build_embeddings(settings), HashEmbeddings)


def test_factory_dashscope_requires_key():
    settings = Settings(_env_file=None, model_provider="dashscope", dashscope_api_key="")
    with pytest.raises(ValueError, match="DASHSCOPE_API_KEY"):
        build_chat_model(settings)
