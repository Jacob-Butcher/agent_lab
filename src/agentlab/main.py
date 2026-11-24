from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from agentlab.api.chat import create_router
from agentlab.config import Settings, get_settings
from agentlab.services import Services, build_services


@asynccontextmanager
async def lifespan(app: FastAPI):
    owned = False
    if app.state.services is None:
        settings: Settings = app.state.settings
        app.state.services = await build_services(settings)
        owned = True
    try:
        yield
    finally:
        if owned:
            await app.state.services.close()


def create_app(settings: Settings | None = None, services: Services | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Agent Lab 智能客服", lifespan=lifespan)
    app.state.settings = settings
    app.state.services = services
    app.include_router(create_router())

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/ready")
    async def ready(request: Request):
        current: Services | None = request.app.state.services
        if current is None:
            return JSONResponse({"status": "not_ready"}, status_code=503)
        ok = await current.store.health() and await current.memory.health()
        return JSONResponse(
            {"status": "ready" if ok else "degraded"}, status_code=200 if ok else 503
        )

    demo_dir = Path(settings.demo_dir)
    if demo_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(demo_dir), html=True), name="demo")

    return app


app = create_app()
