from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant"]
    content: str
    ts: float


@dataclass(frozen=True)
class Chunk:
    doc_id: str
    chunk_index: int
    title: str
    heading: str
    content: str


@dataclass(frozen=True)
class CorpusDoc:
    doc_id: str
    title: str
    doc_hash: str
    chunks: tuple[Chunk, ...]


@dataclass(frozen=True)
class Retrieved:
    doc_id: str
    chunk_index: int
    title: str
    heading: str
    content: str
    score: float

    def to_citation(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "chunk_index": self.chunk_index,
            "title": self.title,
            "heading": self.heading,
            "snippet": self.content[:200],
        }
