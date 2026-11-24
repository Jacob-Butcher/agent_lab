import json

import httpx
import pytest

from agentlab.config import Settings
from agentlab.main import create_app
from agentlab.services import build_services


@pytest.fixture
async def app():
    settings = Settings(
        _env_file=None,
        model_provider="mock",
        memory_backend="memory",
        corpus_dir="data/corpus",
    )
    services = await build_services(settings)
    application = create_app(settings=settings, services=services)
    yield application
    await services.close()


async def test_health(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_chat_sse_events(app):
    body = {
        "session_id": "session-1234",
        "message": "退款多久到账",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/chat", json=body)
    assert response.status_code == 200
    text = response.text
    assert "event: meta" in text
    assert "event: token" in text
    assert "event: done" in text
    done_line = [line for line in text.splitlines() if line.startswith("data:")][-1]
    payload = json.loads(done_line[len("data:") :].strip())
    assert payload["answer"]


async def test_rejects_too_long_message(app):
    body = {"session_id": "session-1234", "message": "x" * 2001}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/chat", json=body)
    assert response.status_code == 400


async def test_history_endpoint(app):
    body = {"session_id": "session-1234", "message": "你好"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        await client.post("/api/chat", json=body)
        response = await client.get("/api/sessions/session-1234/messages")
    assert response.status_code == 200
    assert len(response.json()["messages"]) == 2
