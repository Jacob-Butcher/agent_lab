import hashlib
from pathlib import Path

import frontmatter

from agentlab.models import CorpusDoc
from agentlab.rag.splitter import split_markdown


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_doc(path: Path) -> CorpusDoc:
    post = frontmatter.load(path)
    doc_id = str(post.metadata.get("doc_id") or path.stem)
    title = str(post.metadata.get("title") or path.stem)
    return CorpusDoc(
        doc_id=doc_id,
        title=title,
        doc_hash=sha256_text(post.content),
        chunks=split_markdown(post.content, doc_id, title),
    )


def load_corpus(directory: Path) -> list[CorpusDoc]:
    if not directory.is_dir():
        raise FileNotFoundError(f"corpus directory not found: {directory}")
    docs = [load_doc(p) for p in sorted(directory.glob("*.md"))]
    seen: set[str] = set()
    for doc in docs:
        if doc.doc_id in seen:
            raise ValueError(f"duplicate doc_id: {doc.doc_id}")
        seen.add(doc.doc_id)
    return docs


def load_corpus_dirs(directories: list[Path]) -> list[CorpusDoc]:
    """Load several corpus directories; later directories win on duplicate doc_id.

    Missing paths are skipped. A path that exists but is not a directory raises
    ValueError. Ordering follows the first appearance of each doc_id, so an
    override keeps the position of its first occurrence.
    """
    merged: dict[str, CorpusDoc] = {}
    for directory in directories:
        if not directory.exists():
            continue
        if not directory.is_dir():
            raise ValueError(f"corpus path is not a directory: {directory}")
        for doc in load_corpus(directory):
            merged[doc.doc_id] = doc
    return list(merged.values())
