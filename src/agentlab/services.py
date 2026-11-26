import asyncio
from dataclasses import dataclass
from pathlib import Path

from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from psycopg_pool import AsyncConnectionPool
from redis.asyncio import Redis

from agentlab.config import Settings
from agentlab.graph.build import build_graph
from agentlab.graph.nodes import make_nodes
from agentlab.llm import build_chat_model, build_embeddings
from agentlab.memory import InMemorySessionMemory, RedisSessionMemory, SessionMemory
from agentlab.rag.ingest import ingest_corpus
from agentlab.rag.store import ChunkStore, InMemoryChunkStore, PGChunkStore


@dataclass
class Services:
    settings: Settings
    chat: BaseChatModel
    embeddings: Embeddings
    store: ChunkStore
    memory: SessionMemory
    graph: object

    async def close(self) -> None:
        await self.memory.close()
        await self.store.close()


async def _wait_for(check, timeout: float = 60.0, interval: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        try:
            if await check():
                return
        except Exception:
            pass
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError("dependency did not become ready in time")
        await asyncio.sleep(interval)


async def _pg_ping(pool: AsyncConnectionPool) -> bool:
    async with pool.connection() as conn:
        await conn.execute("SELECT 1")
    return True


async def build_services(settings: Settings) -> Services:
    settings.validate_runtime()
    chat = build_chat_model(settings)
    embeddings = build_embeddings(settings)

    if settings.is_mock or settings.store_backend == "memory":
        store: ChunkStore = InMemoryChunkStore()
        memory: SessionMemory = InMemorySessionMemory(
            max_messages=settings.max_history_messages
        )
    else:
        pool = AsyncConnectionPool(
            settings.postgres_dsn,
            open=False,
            min_size=1,
            max_size=5,
            kwargs={"autocommit": True},
        )
        await pool.open()
        await _wait_for(lambda: _pg_ping(pool))
        pg_store = PGChunkStore(pool, settings.embedding_dim)
        await pg_store.migrate()
        await pg_store.validate_dim(settings.embedding_dim)
        store = pg_store

        if settings.memory_backend == "redis":
            redis = Redis.from_url(settings.redis_url, decode_responses=True)
            redis_memory = RedisSessionMemory(
                redis,
                max_messages=settings.max_history_messages,
                ttl_seconds=settings.session_ttl_seconds,
            )
            await _wait_for(redis_memory.health)
            memory = redis_memory
        else:
            memory = InMemorySessionMemory(max_messages=settings.max_history_messages)

    if settings.ingest_on_startup:
        await ingest_corpus(Path(settings.corpus_dir), store, embeddings)

    nodes = make_nodes(chat, embeddings, store, memory, settings)
    return Services(
        settings=settings,
        chat=chat,
        embeddings=embeddings,
        store=store,
        memory=memory,
        graph=build_graph(nodes),
    )
