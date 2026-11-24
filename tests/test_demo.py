import httpx

from agentlab.config import Settings
from agentlab.main import create_app
from agentlab.services import build_services


async def test_index_page_is_served():
    settings = Settings(
        _env_file=None, model_provider="mock", memory_backend="memory", demo_dir="demo"
    )
    services = await build_services(settings)
    app = create_app(settings=settings, services=services)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/")
        assert response.status_code == 200
        assert "智能客服" in response.text
    finally:
        await services.close()
