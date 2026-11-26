from agentlab.config import Settings
from agentlab.services import build_services

UPLOAD = """---
doc_id: uploaded-faq
title: 上传文档
---
# 上传文档

只存在于 uploads 目录。
"""


async def test_build_services_ingests_upload_dir(tmp_path):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "uploaded-faq.md").write_text(UPLOAD, encoding="utf-8")
    settings = Settings(
        _env_file=None,
        model_provider="mock",
        memory_backend="memory",
        corpus_dir="data/corpus",
        upload_dir=str(uploads),
    )

    services = await build_services(settings)
    try:
        hashes = await services.store.get_doc_hashes()
        assert "uploaded-faq" in hashes
        assert len(hashes) > 1
    finally:
        await services.close()
