import httpx

from agentlab.config import Settings
from agentlab.main import create_app
from agentlab.services import build_services

HEADERS = {"X-Admin-Token": "test-token"}

MD = """---
doc_id: faq-upload
title: 上传测试
---
# 上传测试

## 退款

退款 3 到 7 个工作日到账。
"""


async def _make_app(tmp_path, admin_token="test-token"):
    settings = Settings(
        _env_file=None,
        model_provider="mock",
        memory_backend="memory",
        corpus_dir="data/corpus",
        upload_dir=str(tmp_path / "uploads"),
        admin_token=admin_token,
        max_upload_bytes=5 * 1024 * 1024,
    )
    services = await build_services(settings)
    return create_app(settings=settings, services=services), services


def _client(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def test_requires_configured_token(tmp_path):
    app, services = await _make_app(tmp_path, admin_token="")
    try:
        async with _client(app) as client:
            response = await client.get("/api/kb/docs", headers=HEADERS)
        assert response.status_code == 503
    finally:
        await services.close()


async def test_rejects_wrong_token(tmp_path):
    app, services = await _make_app(tmp_path)
    try:
        async with _client(app) as client:
            response = await client.get(
                "/api/kb/docs", headers={"X-Admin-Token": "nope"}
            )
        assert response.status_code == 401
    finally:
        await services.close()


async def test_upload_list_and_overwrite(tmp_path):
    app, services = await _make_app(tmp_path)
    try:
        async with _client(app) as client:
            first = await client.post(
                "/api/kb/docs",
                headers=HEADERS,
                files={"file": ("faq.md", MD.encode("utf-8"), "text/markdown")},
            )
            assert first.status_code == 201
            assert first.json()["doc_id"] == "faq-upload"

            docs = (await client.get("/api/kb/docs", headers=HEADERS)).json()["docs"]
            uploaded = [doc for doc in docs if doc["doc_id"] == "faq-upload"]
            assert uploaded and uploaded[0]["source"] == "uploads"

            conflict = await client.post(
                "/api/kb/docs",
                headers=HEADERS,
                files={"file": ("faq.md", MD.encode("utf-8"), "text/markdown")},
            )
            assert conflict.status_code == 409

            overwrite = await client.post(
                "/api/kb/docs?overwrite=true",
                headers=HEADERS,
                files={"file": ("faq.md", MD.encode("utf-8"), "text/markdown")},
            )
            assert overwrite.status_code == 201
    finally:
        await services.close()


async def test_upload_rejects_oversized_file(tmp_path):
    app, services = await _make_app(tmp_path)
    try:
        async with _client(app) as client:
            response = await client.post(
                "/api/kb/docs",
                headers=HEADERS,
                files={
                    "file": (
                        "big.md",
                        b"x" * (5 * 1024 * 1024 + 1),
                        "text/markdown",
                    )
                },
            )
        assert response.status_code == 413
    finally:
        await services.close()


async def test_read_and_edit_builtin_creates_override(tmp_path):
    app, services = await _make_app(tmp_path)
    try:
        async with _client(app) as client:
            read = await client.get("/api/kb/docs/coupons", headers=HEADERS)
            assert read.status_code == 200
            payload = read.json()
            assert payload["source"] == "corpus"
            assert "优惠券" in payload["body"]

            new_body = payload["body"] + "\n## 补充\n\n新增规则。\n"
            saved = await client.put(
                "/api/kb/docs/coupons", headers=HEADERS, json={"body": new_body}
            )
            assert saved.status_code == 200
            assert saved.json()["source"] == "uploads"

            docs = (await client.get("/api/kb/docs", headers=HEADERS)).json()["docs"]
            coupons = [doc for doc in docs if doc["doc_id"] == "coupons"]
            assert coupons and coupons[0]["source"] == "uploads"
    finally:
        await services.close()


async def test_delete_override_then_builtin_forbidden(tmp_path):
    app, services = await _make_app(tmp_path)
    try:
        async with _client(app) as client:
            read = await client.get("/api/kb/docs/coupons", headers=HEADERS)
            body = read.json()["body"] + "\n## 补充\n\n新增规则。\n"
            await client.put(
                "/api/kb/docs/coupons", headers=HEADERS, json={"body": body}
            )

            deleted = await client.delete("/api/kb/docs/coupons", headers=HEADERS)
            assert deleted.status_code == 200
            assert deleted.json()["result"] == "reverted_to_builtin"

            forbidden = await client.delete(
                "/api/kb/docs/coupons", headers=HEADERS
            )
            assert forbidden.status_code == 403
    finally:
        await services.close()


async def test_search_clamps_parameters(tmp_path):
    app, services = await _make_app(tmp_path)
    try:
        async with _client(app) as client:
            response = await client.post(
                "/api/kb/search",
                headers=HEADERS,
                json={"query": "退款", "top_k": 999, "threshold": 2},
            )
        assert response.status_code == 200
        assert response.json()["effective"] == {"top_k": 20, "threshold": 1.0}
    finally:
        await services.close()


async def test_unknown_doc_returns_404(tmp_path):
    app, services = await _make_app(tmp_path)
    try:
        async with _client(app) as client:
            response = await client.get("/api/kb/docs/nope", headers=HEADERS)
        assert response.status_code == 404
    finally:
        await services.close()


async def test_rejects_non_ascii_token(tmp_path):
    app, services = await _make_app(tmp_path)
    try:
        async with _client(app) as client:
            response = await client.get(
                "/api/kb/docs",
                headers={"X-Admin-Token": "éé".encode("latin-1")},
            )
        assert response.status_code == 401
    finally:
        await services.close()


async def test_missing_token_rejected(tmp_path):
    app, services = await _make_app(tmp_path)
    try:
        async with _client(app) as client:
            response = await client.get("/api/kb/docs")
        assert response.status_code == 401
    finally:
        await services.close()


async def test_upload_rejects_non_markdown(tmp_path):
    app, services = await _make_app(tmp_path)
    try:
        async with _client(app) as client:
            response = await client.post(
                "/api/kb/docs",
                headers=HEADERS,
                files={"file": ("notes.csv", b"a,b\n1,2\n", "text/csv")},
            )
        assert response.status_code == 400
    finally:
        await services.close()


async def test_whitespace_body_and_query_rejected(tmp_path):
    app, services = await _make_app(tmp_path)
    try:
        async with _client(app) as client:
            put = await client.put(
                "/api/kb/docs/coupons", headers=HEADERS, json={"body": "   "}
            )
            assert put.status_code == 400
            search = await client.post(
                "/api/kb/search", headers=HEADERS, json={"query": "   "}
            )
            assert search.status_code == 400
    finally:
        await services.close()


async def test_put_rejects_oversized_body(tmp_path):
    app, services = await _make_app(tmp_path)
    try:
        async with _client(app) as client:
            read = await client.get("/api/kb/docs/coupons", headers=HEADERS)
            big = read.json()["body"] + "x" * (5 * 1024 * 1024)
            response = await client.put(
                "/api/kb/docs/coupons", headers=HEADERS, json={"body": big}
            )
        assert response.status_code == 413
    finally:
        await services.close()


async def test_admin_page_served(tmp_path):
    app, services = await _make_app(tmp_path)
    try:
        async with _client(app) as client:
            response = await client.get("/admin/kb")
        assert response.status_code == 200
        assert "知识库管理" in response.text
    finally:
        await services.close()


async def test_admin_static_paths(tmp_path):
    app, services = await _make_app(tmp_path)
    try:
        async with _client(app) as client:
            page = await client.get("/admin/kb")
            assert page.headers["content-type"].startswith("text/html")
            static = await client.get("/admin/kb.html")
            assert static.status_code == 200
            missing = await client.get("/admin/nope")
            assert missing.status_code == 404
    finally:
        await services.close()


async def test_upload_docx_returns_format(tmp_path):
    from tests.docgen import make_docx

    app, services = await _make_app(tmp_path)
    try:
        async with _client(app) as client:
            response = await client.post(
                "/api/kb/docs",
                headers=HEADERS,
                files={
                    "file": (
                        "refund.docx",
                        make_docx(),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                },
            )
        assert response.status_code == 201
        payload = response.json()
        assert payload["format"] == "docx"
        assert payload["doc_id"].startswith("docx-")
    finally:
        await services.close()


async def test_upload_txt_with_optional_doc_id(tmp_path):
    app, services = await _make_app(tmp_path)
    try:
        async with _client(app) as client:
            response = await client.post(
                "/api/kb/docs",
                headers=HEADERS,
                data={"doc_id": "policy-txt"},
                files={"file": ("policy.txt", "售后政策".encode(), "text/plain")},
            )
        assert response.status_code == 201
        assert response.json()["doc_id"] == "policy-txt"
        assert response.json()["format"] == "txt"
    finally:
        await services.close()


async def test_admin_page_supports_multi_format_upload(tmp_path):
    app, services = await _make_app(tmp_path)
    try:
        async with _client(app) as client:
            response = await client.get("/admin/kb")
        assert 'accept=".md,.txt,.pdf,.docx,.pptx"' in response.text
        assert 'id="doc-id"' in response.text
        assert "≤50MB" in response.text
    finally:
        await services.close()
