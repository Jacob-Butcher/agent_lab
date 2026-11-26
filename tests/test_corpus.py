from pathlib import Path

import pytest

from agentlab.rag.corpus import load_corpus, load_corpus_dirs


def test_corpus_has_30_unique_docs():
    docs = load_corpus(Path("data/corpus"))
    assert len(docs) == 30
    assert len({d.doc_id for d in docs}) == 30
    assert all(d.chunks for d in docs)


def test_corpus_covers_core_topics():
    ids = {d.doc_id for d in load_corpus(Path("data/corpus"))}
    for required in ("no-reason-return", "refund-timeline", "invoice", "logistics-tracking"):
        assert required in ids


def test_load_corpus_dirs_later_overrides(tmp_path):
    corpus = tmp_path / "corpus"
    uploads = tmp_path / "uploads"
    corpus.mkdir()
    uploads.mkdir()
    (corpus / "a.md").write_text(
        "---\ndoc_id: a\ntitle: A\n---\n# A\n\n旧内容\n", encoding="utf-8"
    )
    (uploads / "a.md").write_text(
        "---\ndoc_id: a\ntitle: A\n---\n# A\n\n新内容\n", encoding="utf-8"
    )
    docs = load_corpus_dirs([corpus, uploads])
    assert len(docs) == 1
    assert any("新内容" in chunk.content for chunk in docs[0].chunks)
    assert not any("旧内容" in chunk.content for chunk in docs[0].chunks)


def test_load_corpus_dirs_ignores_missing_dir(tmp_path):
    assert load_corpus_dirs([tmp_path / "none"]) == []


def test_load_corpus_dirs_rejects_duplicate_within_dir(tmp_path):
    (tmp_path / "a.md").write_text(
        "---\ndoc_id: dup\ntitle: A\n---\n# A\n\n甲\n", encoding="utf-8"
    )
    (tmp_path / "b.md").write_text(
        "---\ndoc_id: dup\ntitle: B\n---\n# B\n\n乙\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="duplicate doc_id"):
        load_corpus_dirs([tmp_path])


def test_load_corpus_dirs_merges_union(tmp_path):
    corpus = tmp_path / "corpus"
    uploads = tmp_path / "uploads"
    corpus.mkdir()
    uploads.mkdir()
    (corpus / "a.md").write_text(
        "---\ndoc_id: a\ntitle: A\n---\n# A\n\n旧内容\n", encoding="utf-8"
    )
    (corpus / "b.md").write_text(
        "---\ndoc_id: b\ntitle: B\n---\n# B\n\n只有内置\n", encoding="utf-8"
    )
    (uploads / "a.md").write_text(
        "---\ndoc_id: a\ntitle: A\n---\n# A\n\n新内容\n", encoding="utf-8"
    )

    docs = load_corpus_dirs([corpus, uploads])

    assert {doc.doc_id for doc in docs} == {"a", "b"}
    a = next(doc for doc in docs if doc.doc_id == "a")
    assert any("新内容" in chunk.content for chunk in a.chunks)
    assert not any("旧内容" in chunk.content for chunk in a.chunks)


def test_load_corpus_dirs_rejects_file_path(tmp_path):
    not_a_dir = tmp_path / "file.md"
    not_a_dir.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="not a directory"):
        load_corpus_dirs([not_a_dir])
