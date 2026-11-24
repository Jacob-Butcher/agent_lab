import asyncio
import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from agentlab.services import Services


class ChatRequest(BaseModel):
    session_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,64}$")
    message: str = Field(min_length=1)


def get_services(request: Request) -> Services:
    services = request.app.state.services
    if services is None:
        raise HTTPException(status_code=503, detail="services not ready")
    return services


def _sse(event: str, data: dict[str, Any]) -> dict[str, str]:
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}


def _chunk_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


def create_router() -> APIRouter:
    router = APIRouter()
    locks: dict[str, asyncio.Lock] = {}

    @router.post("/api/chat")
    async def chat(
        body: ChatRequest,
        services: Annotated[Services, Depends(get_services)],
    ):
        if len(body.message) > services.settings.max_message_chars:
            raise HTTPException(
                status_code=400,
                detail=f"message exceeds {services.settings.max_message_chars} characters",
            )

        lock = locks.setdefault(body.session_id, asyncio.Lock())

        async def events():
            yield _sse("meta", {"session_id": body.session_id})
            citations: list[dict] = []
            answer = ""
            try:
                async with lock:
                    async for mode, payload in services.graph.astream(
                        {"query": body.message, "session_id": body.session_id},
                        stream_mode=["messages", "updates"],
                    ):
                        if mode == "messages":
                            chunk, metadata = payload
                            if metadata.get("langgraph_node") == "respond":
                                text = _chunk_text(chunk.content)
                                if text:
                                    yield _sse("token", {"text": text})
                        elif mode == "updates":
                            for node, update in payload.items():
                                if node == "retrieve":
                                    citations = update.get("citations", [])
                                    for citation in citations:
                                        yield _sse("citation", citation)
                                if node == "respond":
                                    answer = update.get("answer", "")
                yield _sse("done", {"answer": answer, "citations": citations})
            except Exception:
                yield _sse(
                    "error",
                    {"code": "internal_error", "message": "服务暂时不可用，请稍后重试。"},
                )

        return EventSourceResponse(
            events(),
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.get("/api/sessions/{session_id}/messages")
    async def history(
        session_id: str,
        services: Annotated[Services, Depends(get_services)],
    ):
        messages = await services.memory.load(session_id, 50)
        return {
            "messages": [
                {"role": m.role, "content": m.content, "ts": m.ts} for m in messages
            ]
        }

    return router
