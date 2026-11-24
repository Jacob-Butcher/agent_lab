from pathlib import Path

from agentlab.rag.corpus import load_corpus


def test_corpus_has_30_unique_docs():
    docs = load_corpus(Path("data/corpus"))
    assert len(docs) == 30
    assert len({d.doc_id for d in docs}) == 30
    assert all(d.chunks for d in docs)


def test_corpus_covers_core_topics():
    ids = {d.doc_id for d in load_corpus(Path("data/corpus"))}
    for required in ("no-reason-return", "refund-timeline", "invoice", "logistics-tracking"):
        assert required in ids
