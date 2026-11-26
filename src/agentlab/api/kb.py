import secrets
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from pydantic import BaseModel, Field

from agentlab.kb import KbError, KBManager
from agentlab.services import Services


def require_admin(request: Request) -> KBManager:
    services: Services | None = request.app.state.services
    if services is None:
        raise HTTPException(status_code=503, detail="services not ready")
    settings = services.settings
    if not settings.admin_token:
        raise HTTPException(
            status_code=503, detail="知识库管理未启用，请配置 ADMIN_TOKEN"
        )
    token = request.headers.get("X-Admin-Token", "")
    if not secrets.compare_digest(
        token.encode("utf-8"), settings.admin_token.encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="无效的管理令牌")
    return services.kb


class SaveBody(BaseModel):
    body: str = Field(min_length=1)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int | None = None
    threshold: float | None = None


def create_kb_router() -> APIRouter:
    router = APIRouter(prefix="/api/kb")
    Admin = Annotated[KBManager, Depends(require_admin)]

    @router.get("/docs")
    async def list_docs(kb: Admin):
        return {"docs": await kb.list_docs()}

    @router.get("/docs/{doc_id}")
    async def get_doc(doc_id: str, kb: Admin):
        return await kb.get_doc(doc_id)

    @router.post("/docs", status_code=201)
    async def upload_doc(
        kb: Admin,
        file: Annotated[UploadFile, File()],
        overwrite: bool = False,
        doc_id: Annotated[str | None, Form()] = None,
    ):
        if not file.filename:
            raise KbError(400, "缺少文件名")
        data = await file.read(kb.settings.max_upload_bytes + 1)
        return await kb.upload(
            file.filename, data, overwrite=overwrite, doc_id=doc_id
        )

    @router.put("/docs/{doc_id}")
    async def save_doc(doc_id: str, payload: SaveBody, kb: Admin):
        return await kb.save_body(doc_id, payload.body)

    @router.delete("/docs/{doc_id}")
    async def delete_doc(doc_id: str, kb: Admin):
        return await kb.delete(doc_id)

    @router.post("/search")
    async def search(payload: SearchRequest, kb: Admin):
        return await kb.search(
            payload.query, top_k=payload.top_k, threshold=payload.threshold
        )

    return router
