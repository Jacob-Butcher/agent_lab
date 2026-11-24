import hashlib
import math
from collections.abc import AsyncIterator, Iterator

from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from agentlab.config import Settings


class HashEmbeddings(Embeddings):
    """Deterministic character-bigram hashing; for plumbing tests only."""

    def __init__(self, dim: int = 1024) -> None:
        if dim <= 0:
            raise ValueError("dim must be positive")
        self.dim = dim

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = [text[i] for i in range(len(text))]
        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            vec[int.from_bytes(digest, "big") % self.dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class MockChatModel(BaseChatModel):
    """Streaming mock that echoes the last question; for tests and local demo."""

    @property
    def _llm_type(self) -> str:
        return "mock"

    @staticmethod
    def _answer(messages: list[BaseMessage]) -> str:
        last = str(messages[-1].content) if messages else ""
        return f"这是模拟回答。关于「{last[:40]}」，请以知识库资料为准。[mock#0]"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager=None,
        **kwargs,
    ) -> ChatResult:
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=self._answer(messages)))]
        )

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager=None,
        **kwargs,
    ) -> Iterator[ChatGenerationChunk]:
        for char in self._answer(messages):
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=char))
            if run_manager is not None:
                run_manager.on_llm_new_token(char, chunk=chunk)
            yield chunk

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager=None,
        **kwargs,
    ) -> AsyncIterator[ChatGenerationChunk]:
        for char in self._answer(messages):
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=char))
            if run_manager is not None:
                await run_manager.on_llm_new_token(char, chunk=chunk)
            yield chunk


def build_chat_model(settings: Settings) -> BaseChatModel:
    settings.validate_runtime()
    if settings.is_mock:
        return MockChatModel()
    return ChatOpenAI(
        model=settings.chat_model,
        api_key=settings.dashscope_api_key,
        base_url=settings.dashscope_base_url,
        temperature=0.2,
        streaming=True,
        timeout=60,
        max_retries=2,
    )


def build_embeddings(settings: Settings) -> Embeddings:
    settings.validate_runtime()
    if settings.is_mock:
        return HashEmbeddings(dim=settings.embedding_dim)
    return OpenAIEmbeddings(
        model=settings.embedding_model,
        api_key=settings.dashscope_api_key,
        base_url=settings.dashscope_base_url,
        dimensions=settings.embedding_dim,
        chunk_size=settings.embed_batch_size,
        check_embedding_ctx_length=False,
    )
