import asyncio
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import frontmatter
from langchain_core.embeddings import Embeddings

from agentlab.config import Settings
from agentlab.models import Chunk, DocInfo
from agentlab.rag.corpus import load_doc, sha256_text
from agentlab.rag.splitter import split_markdown
from agentlab.rag.store import ChunkStore

DOC_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
PREVIEW_CHARS = 200


class KbError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _iso(mtime: float) -> str:
    return datetime.fromtimestamp(mtime, tz=UTC).isoformat()


class KBManager:
    """Writes are serialized by an asyncio.Lock; reads are unlocked.

    Reads are eventually consistent: they see the on-disk files without
    acquiring the lock (safe because everything runs on one event loop).
    """

    def __init__(
        self, settings: Settings, store: ChunkStore, embeddings: Embeddings
    ) -> None:
        self.settings = settings
        self.store = store
        self.embeddings = embeddings
        self.corpus_dir = Path(settings.corpus_dir)
        self.upload_dir = Path(settings.upload_dir)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    def _scan_dir(self, directory: Path) -> dict[str, Path]:
        result: dict[str, Path] = {}
        if not directory.is_dir():
            return result
        for path in sorted(directory.glob("*.md")):
            try:
                post = frontmatter.load(path)
            except Exception as exc:
                raise KbError(500, f"文档解析失败：{path.name}") from exc
            doc_id = str(post.metadata.get("doc_id") or path.stem)
            if doc_id in result:
                raise KbError(500, f"目录 {directory} 内 doc_id 重复：{doc_id}")
            result[doc_id] = path
        return result

    def _file_index(self) -> dict[str, tuple[Path, str]]:
        index: dict[str, tuple[Path, str]] = {}
        for doc_id, path in self._scan_dir(self.corpus_dir).items():
            index[doc_id] = (path, "corpus")
        for doc_id, path in self._scan_dir(self.upload_dir).items():
            index[doc_id] = (path, "uploads")
        return index

    @staticmethod
    def _read(path: Path) -> tuple[dict[str, Any], str]:
        post = frontmatter.load(path)
        return dict(post.metadata), post.content

    @staticmethod
    def _write_atomic(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.stem}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
            os.replace(tmp, path)
        finally:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass

    def _upload_path(self, doc_id: str) -> Path:
        return self.upload_dir / f"{doc_id}.md"

    def _remove_stale_upload(self, doc_id: str) -> None:
        target = self._upload_path(doc_id)
        for path in sorted(self.upload_dir.glob("*.md")):
            if path == target:
                continue
            try:
                post = frontmatter.load(path)
            except Exception:
                continue
            if str(post.metadata.get("doc_id") or path.stem) == doc_id:
                path.unlink()

    async def _embed(self, chunks: list[Chunk]) -> list[list[float]]:
        texts = [chunk.content for chunk in chunks]
        vectors: list[list[float]] = []
        batch = self.settings.embed_batch_size
        try:
            for start in range(0, len(texts), batch):
                vectors.extend(
                    await self.embeddings.aembed_documents(texts[start : start + batch])
                )
        except Exception as exc:
            raise KbError(502, "向量化失败，请检查 embedding 配置或稍后重试") from exc
        return vectors

    async def _save_index(
        self, doc_id: str, body: str, chunks: list[Chunk], vectors: list[list[float]]
    ) -> None:
        try:
            await self.store.replace_doc(doc_id, sha256_text(body), chunks, vectors)
        except Exception as exc:
            raise KbError(502, "源文件已保存，索引写入失败，重启后会自动重建") from exc

    async def list_docs(self) -> list[dict]:
        infos: list[DocInfo] = await self.store.list_docs()
        files = self._file_index()
        docs: list[dict] = []
        for info in infos:
            entry = files.get(info.doc_id)
            docs.append(
                {
                    "doc_id": info.doc_id,
                    "title": info.title,
                    "chunks": info.chunks,
                    "source": entry[1] if entry else "uploads",
                    "updated_at": _iso(entry[0].stat().st_mtime) if entry else None,
                }
            )
        return docs

    async def get_doc(self, doc_id: str) -> dict:
        entry = self._file_index().get(doc_id)
        if entry is None:
            raise KbError(404, f"文档不存在：{doc_id}")
        path, source = entry
        metadata, body = self._read(path)
        return {
            "doc_id": doc_id,
            "title": str(metadata.get("title") or doc_id),
            "body": body,
            "source": source,
        }

    async def upload(self, filename: str, data: bytes, overwrite: bool = False) -> dict:
        if not filename.lower().endswith(".md"):
            raise KbError(400, "仅支持 .md 文件")
        if len(data) > self.settings.max_upload_bytes:
            raise KbError(413, f"文件超过 {self.settings.max_upload_bytes} 字节限制")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise KbError(400, "文件必须是 UTF-8 编码") from exc

        try:
            post = frontmatter.loads(text)
        except Exception as exc:
            raise KbError(400, "frontmatter 解析失败，请检查 YAML 格式") from exc
        doc_id = str(post.metadata.get("doc_id") or Path(filename).stem)
        if not DOC_ID_PATTERN.match(doc_id):
            raise KbError(
                400, "doc_id 只能包含小写字母、数字、点、下划线、短横线，且不超过 64 字符"
            )
        title = str(post.metadata.get("title") or doc_id)
        body = post.content.strip()
        if not body:
            raise KbError(400, "文档正文为空")

        async with self._lock:
            existing = self._file_index().get(doc_id)
            if existing and not overwrite:
                raise KbError(409, f"doc_id 已存在：{doc_id}，是否覆盖？")
            chunks = list(split_markdown(body, doc_id, title))
            if not chunks:
                raise KbError(400, "文档切块后为空")

            post.content = body
            post.metadata["doc_id"] = doc_id
            post.metadata.setdefault("title", title)
            vectors = await self._embed(chunks)
            self._write_atomic(self._upload_path(doc_id), frontmatter.dumps(post))
            self._remove_stale_upload(doc_id)
            await self._save_index(doc_id, body, chunks, vectors)
            return {"doc_id": doc_id, "title": title, "chunks": len(chunks), "source": "uploads"}

    async def save_body(self, doc_id: str, body: str) -> dict:
        if not DOC_ID_PATTERN.match(doc_id):
            raise KbError(400, "doc_id 不合法")
        body = body.strip()
        if not body:
            raise KbError(400, "正文不能为空")

        async with self._lock:
            entry = self._file_index().get(doc_id)
            if entry is None:
                raise KbError(404, f"文档不存在：{doc_id}")
            metadata, _ = self._read(entry[0])
            title = str(metadata.get("title") or doc_id)
            chunks = list(split_markdown(body, doc_id, title))
            if not chunks:
                raise KbError(400, "正文切块后为空")

            metadata["doc_id"] = doc_id
            metadata.setdefault("title", title)
            post = frontmatter.Post(body)
            post.metadata = metadata
            vectors = await self._embed(chunks)
            self._write_atomic(self._upload_path(doc_id), frontmatter.dumps(post))
            self._remove_stale_upload(doc_id)
            await self._save_index(doc_id, body, chunks, vectors)
            return {"doc_id": doc_id, "chunks": len(chunks), "source": "uploads"}

    async def delete(self, doc_id: str) -> dict:
        async with self._lock:
            uploads = self._scan_dir(self.upload_dir)
            corpus = self._scan_dir(self.corpus_dir)
            upload_path = uploads.get(doc_id)
            if upload_path is not None:
                if doc_id in corpus:
                    doc = load_doc(corpus[doc_id])
                    chunks = list(doc.chunks)
                    vectors = await self._embed(chunks)
                    upload_path.unlink()
                    try:
                        await self.store.replace_doc(
                            doc.doc_id, doc.doc_hash, chunks, vectors
                        )
                    except Exception as exc:
                        raise KbError(
                            502, "源文件已删除，索引回退失败，重启后会自动重建"
                        ) from exc
                    return {"doc_id": doc_id, "result": "reverted_to_builtin"}
                upload_path.unlink()
                try:
                    await self.store.delete_doc(doc_id)
                except Exception as exc:
                    raise KbError(502, "索引删除失败，请稍后重试") from exc
                return {"doc_id": doc_id, "result": "deleted_override"}
            if doc_id in corpus:
                raise KbError(403, "内置文档由 git 管理；如需修改请先编辑生成覆盖版本")
            raise KbError(404, f"文档不存在：{doc_id}")
