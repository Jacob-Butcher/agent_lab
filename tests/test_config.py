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
