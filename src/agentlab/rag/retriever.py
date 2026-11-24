from dataclasses import dataclass

from langchain_core.embeddings import Embeddings

from agentlab.models import Retrieved
from agentlab.rag.store import ChunkStore


@dataclass(frozen=True)
class RetrievalResult:
    chunks: list[Retrieved]
    citations: list[dict]
    context: str


async def retrieve(
    query: str,
    embeddings: Embeddings,
    store: ChunkStore,
    top_k: int,
    threshold: float,
) -> RetrievalResult:
    vector = await embeddings.aembed_query(query)
    rows = await store.search(vector, k=top_k, threshold=threshold)

    seen: set[tuple[str, int]] = set()
    unique: list[Retrieved] = []
    for row in rows:
        key = (row.doc_id, row.chunk_index)
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)

    citations = [row.to_citation() for row in unique]
    context = "\n\n".join(
        f"[{row.doc_id}#{row.chunk_index}] {row.title} / {row.heading}\n{row.content}"
        for row in unique
    )
    return RetrievalResult(chunks=unique, citations=citations, context=context)
