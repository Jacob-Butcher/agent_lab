import pytest
from pydantic import ValidationError

from agentlab.config import Settings


def _settings(**kwargs):
    return Settings(_env_file=None, **kwargs)


def test_mock_provider_needs_no_api_key():
    s = _settings(model_provider="mock")
    s.validate_runtime()
    assert s.is_mock is True


def test_dashscope_requires_api_key():
    s = _settings(model_provider="dashscope", dashscope_api_key="")
    with pytest.raises(ValueError, match="DASHSCOPE_API_KEY"):
        s.validate_runtime()


def test_invalid_provider_rejected():
    with pytest.raises(ValidationError):
        _settings(model_provider="nope")


def test_defaults():
    s = _settings()
    assert s.embedding_dim == 1024
    assert s.rag_top_k == 5
    assert s.max_history_messages == 12


def test_kb_defaults():
    s = _settings()
    assert s.upload_dir == "data/uploads"
    assert s.admin_token == ""
    assert s.max_upload_bytes == 50 * 1024 * 1024


def test_document_parsing_defaults():
    s = _settings()
    assert s.max_doc_pages == 100
    assert s.max_doc_chars == 2_000_000
    assert s.image_ocr_enabled is True
    assert s.ocr_model == "qwen-vl-ocr"
    assert s.max_zip_uncompressed == 200 * 1024 * 1024
    assert s.max_zip_entries == 5000


def test_settings_env_override(monkeypatch):
    monkeypatch.setenv("MAX_DOC_PAGES", "7")
    s = Settings(_env_file=None)
    assert s.max_doc_pages == 7


def test_invalid_parsing_limits_rejected():
    with pytest.raises(ValueError, match="MAX_DOC_PAGES"):
        _settings(model_provider="mock", max_doc_pages=0).validate_runtime()
