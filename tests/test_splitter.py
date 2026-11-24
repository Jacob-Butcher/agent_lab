from pathlib import Path

import pytest

from agentlab.rag.corpus import load_corpus, load_doc
from agentlab.rag.splitter import split_markdown

SAMPLE = """---
doc_id: returns
title: 退换货政策
access_level: public
---
# 退换货政策

本政策适用于星选商城自营商品。

## 适用范围

签收后 7 天内可申请无理由退货，商品需保持完好。

## 时效

质量问题请在签收后 15 天内提交申请，并附图片或视频。
"""


def test_split_keeps_metadata_and_content(tmp_path: Path):
    path = tmp_path / "returns.md"
    path.write_text(SAMPLE, encoding="utf-8")
    doc = load_doc(path)
    assert doc.doc_id == "returns"
    assert doc.title == "退换货政策"
    assert len(doc.chunks) >= 2
    assert all(c.doc_id == "returns" for c in doc.chunks)
    assert any("7 天" in c.content for c in doc.chunks)
    assert all(len(c.content) <= 600 for c in doc.chunks)


def test_doc_hash_changes_when_content_changes(tmp_path: Path):
    p1 = tmp_path / "a.md"
    p1.write_text(SAMPLE, encoding="utf-8")
    h1 = load_doc(p1).doc_hash
    p1.write_text(SAMPLE.replace("7 天", "3 天"), encoding="utf-8")
    assert load_doc(p1).doc_hash != h1


def test_load_corpus_rejects_duplicate_doc_ids(tmp_path: Path):
    (tmp_path / "a.md").write_text(SAMPLE, encoding="utf-8")
    (tmp_path / "b.md").write_text(SAMPLE, encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate doc_id"):
        load_corpus(tmp_path)


def test_split_markdown_without_frontmatter():
    chunks = split_markdown("# 标题\n\n## 小节\n\n内容", "doc", "标题")
    assert chunks
    assert chunks[0].doc_id == "doc"
