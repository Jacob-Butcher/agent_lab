from dataclasses import dataclass
from pathlib import Path

from langchain_core.embeddings import Embeddings

from agentlab.rag.corpus import load_corpus
from agentlab.rag.store import ChunkStore


@dataclass
class IngestStats:
    added: int = 0
    changed: int = 0
    skipped: int = 0
    deleted: int = 0
    chunks: int = 0


async def ingest_corpus(
    corpus_dir: Path,
    store: ChunkStore,
    embeddings: Embeddings,
    batch_size: int = 10,
    reset: bool = False,
) -> IngestStats:
    docs = load_corpus(corpus_dir)
    existing = {} if reset else await store.get_doc_hashes()
    stats = IngestStats()

    for doc in docs:
        if not reset and existing.get(doc.doc_id) == doc.doc_hash:
            stats.skipped += 1
            continue
        if not doc.chunks:
            continue
        if doc.doc_id in existing:
            stats.changed += 1
        else:
            stats.added += 1

        texts = [chunk.content for chunk in doc.chunks]
        vectors: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            vectors.extend(
                await embeddings.aembed_documents(texts[start : start + batch_size])
            )

        await store.replace_doc(doc.doc_id, doc.doc_hash, list(doc.chunks), vectors)
        stats.chunks += len(doc.chunks)

    current_ids = {doc.doc_id for doc in docs}
    for doc_id in set(existing) - current_ids:
        await store.delete_doc(doc_id)
        stats.deleted += 1

    return stats
