import math
from typing import Protocol

from agentlab.models import Chunk, Retrieved
from agentlab.rag.corpus import sha256_text


class ChunkStore(Protocol):
    async def migrate(self) -> None: ...
    async def validate_dim(self, dim: int) -> None: ...
    async def get_doc_hashes(self) -> dict[str, str]: ...
    async def replace_doc(
        self, doc_id: str, doc_hash: str, chunks: list[Chunk], embeddings: list[list[float]]
    ) -> None: ...
    async def delete_doc(self, doc_id: str) -> None: ...
    async def search(
        self, query_embedding: list[float], k: int, threshold: float
    ) -> list[Retrieved]: ...
    async def health(self) -> bool: ...
    async def close(self) -> None: ...


def parse_vector_dim(type_name: str) -> int:
    if not type_name.startswith("vector(") or not type_name.endswith(")"):
        raise ValueError(f"not a vector column: {type_name}")
    return int(type_name[len("vector(") : -1])


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vector) + "]"


class InMemoryChunkStore:
    def __init__(self) -> None:
        self._rows: dict[tuple[str, int], tuple[Chunk, list[float]]] = {}
        self._hashes: dict[str, str] = {}

    async def migrate(self) -> None:
        return None

    async def validate_dim(self, dim: int) -> None:
        for _, vector in self._rows.values():
            if len(vector) != dim:
                raise ValueError(f"embedding dim {len(vector)} != expected {dim}")

    async def get_doc_hashes(self) -> dict[str, str]:
        return dict(self._hashes)

    async def replace_doc(
        self, doc_id: str, doc_hash: str, chunks: list[Chunk], embeddings: list[list[float]]
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings length mismatch")
        for key in [k for k in self._rows if k[0] == doc_id]:
            del self._rows[key]
        for chunk, vector in zip(chunks, embeddings, strict=True):
            self._rows[(chunk.doc_id, chunk.chunk_index)] = (chunk, vector)
        self._hashes[doc_id] = doc_hash

    async def delete_doc(self, doc_id: str) -> None:
        for key in [k for k in self._rows if k[0] == doc_id]:
            del self._rows[key]
        self._hashes.pop(doc_id, None)

    async def search(
        self, query_embedding: list[float], k: int, threshold: float
    ) -> list[Retrieved]:
        scored: list[Retrieved] = []
        for chunk, vector in self._rows.values():
            score = _cosine(query_embedding, vector)
            if score >= threshold:
                scored.append(
                    Retrieved(
                        doc_id=chunk.doc_id,
                        chunk_index=chunk.chunk_index,
                        title=chunk.title,
                        heading=chunk.heading,
                        content=chunk.content,
                        score=score,
                    )
                )
        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:k]

    async def health(self) -> bool:
        return True

    async def close(self) -> None:
        return None


class PGChunkStore:
    def __init__(self, pool, dim: int) -> None:
        self.pool = pool
        self.dim = dim

    async def migrate(self) -> None:
        async with self.pool.connection() as conn:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            await conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS kb_chunks (
                  id BIGSERIAL PRIMARY KEY,
                  doc_id TEXT NOT NULL,
                  chunk_index INT NOT NULL,
                  title TEXT NOT NULL,
                  heading TEXT NOT NULL DEFAULT '',
                  content TEXT NOT NULL,
                  metadata JSONB NOT NULL DEFAULT '{{}}',
                  embedding vector({self.dim}) NOT NULL,
                  content_hash TEXT NOT NULL,
                  UNIQUE (doc_id, chunk_index)
                )
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS kb_chunks_embedding_idx
                ON kb_chunks USING hnsw (embedding vector_cosine_ops)
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ingest_state (
                  doc_id TEXT PRIMARY KEY,
                  doc_hash TEXT NOT NULL
                )
                """
            )

    async def validate_dim(self, dim: int) -> None:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                """
                SELECT format_type(atttypid, atttypmod)
                FROM pg_attribute
                WHERE attrelid = 'kb_chunks'::regclass AND attname = 'embedding'
                """
            )
            row = await cur.fetchone()
        if not row:
            raise ValueError("kb_chunks.embedding column not found")
        actual = parse_vector_dim(row[0])
        if actual != dim:
            raise ValueError(
                f"kb_chunks.embedding is vector({actual}), expected vector({dim})"
            )

    async def get_doc_hashes(self) -> dict[str, str]:
        async with self.pool.connection() as conn:
            cur = await conn.execute("SELECT doc_id, doc_hash FROM ingest_state")
            rows = await cur.fetchall()
        return {row[0]: row[1] for row in rows}

    async def replace_doc(
        self, doc_id: str, doc_hash: str, chunks: list[Chunk], embeddings: list[list[float]]
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings length mismatch")
        records = [
            (
                chunk.doc_id,
                chunk.chunk_index,
                chunk.title,
                chunk.heading,
                chunk.content,
                "{}",
                _vector_literal(vector),
                sha256_text(chunk.content),
            )
            for chunk, vector in zip(chunks, embeddings, strict=True)
        ]
        async with self.pool.connection() as conn:
            async with conn.transaction():
                await conn.execute("DELETE FROM kb_chunks WHERE doc_id = %s", (doc_id,))
                await conn.executemany(
                    """
                    INSERT INTO kb_chunks
                      (doc_id, chunk_index, title, heading,
                       content, metadata, embedding, content_hash)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::vector, %s)
                    """,
                    records,
                )
                await conn.execute(
                    """
                    INSERT INTO ingest_state (doc_id, doc_hash) VALUES (%s, %s)
                    ON CONFLICT (doc_id) DO UPDATE SET doc_hash = EXCLUDED.doc_hash
                    """,
                    (doc_id, doc_hash),
                )

    async def delete_doc(self, doc_id: str) -> None:
        async with self.pool.connection() as conn:
            async with conn.transaction():
                await conn.execute("DELETE FROM kb_chunks WHERE doc_id = %s", (doc_id,))
                await conn.execute("DELETE FROM ingest_state WHERE doc_id = %s", (doc_id,))

    async def search(
        self, query_embedding: list[float], k: int, threshold: float
    ) -> list[Retrieved]:
        literal = _vector_literal(query_embedding)
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                """
                SELECT doc_id, chunk_index, title, heading, content,
                       1 - (embedding <=> %s::vector) AS score
                FROM kb_chunks
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (literal, literal, k),
            )
            rows = await cur.fetchall()
        results = [
            Retrieved(
                doc_id=row[0],
                chunk_index=row[1],
                title=row[2],
                heading=row[3],
                content=row[4],
                score=float(row[5]),
            )
            for row in rows
        ]
        return [r for r in results if r.score >= threshold]

    async def health(self) -> bool:
        try:
            async with self.pool.connection() as conn:
                await conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    async def close(self) -> None:
        await self.pool.close()
