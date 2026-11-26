# Agent Lab 知识库管理（KB Admin）设计

日期：2026-11-26
状态：已评审待实现

## 背景与目标

当前知识库只能通过 `data/corpus/*.md` + 重新部署维护，没有运行时上传入口，调优检索参数（`RAG_TOP_K`、`RAG_SCORE_THRESHOLD`）也没有直观的分数反馈。

目标：

- 提供同源管理页 `/admin/kb`，支持上传 `.md`、查看/编辑正文、删除、检索预览
- 上传的源文件持久化，重启不丢
- 内置语料（git 管理的 `data/corpus/`）与上传内容可共存，可覆盖、可回退
- 不影响现有聊天链路与测试

非目标：

- 不做 SPA / 前后端分工程（无 Node 构建、无 CORS）
- 不做多用户账号体系（单一 `ADMIN_TOKEN`）
- 不支持在页面修改 `doc_id` / `title`，不支持批量上传与全量重建按钮
- 不直接编辑 `kb_chunks` 向量表（向量为派生数据）

## 架构

```
浏览器 /admin/kb ── fetch(X-Admin-Token) ──► FastAPI /api/kb/*
                                                  │
                                     kb.py: KBManager（asyncio.Lock）
                                                  │
        split_markdown / embeddings / store.replace_doc / delete_doc
                                                  │
                                     data/uploads/<doc_id>.md（源文件）
```

### 模块划分

| 文件 | 职责 |
|---|---|
| `src/agentlab/kb.py`（新） | `KBManager`：列表、读取正文、保存/编辑、删除、检索预览；持有写锁 |
| `src/agentlab/api/kb.py`（新） | 路由与 `X-Admin-Token` 鉴权依赖 |
| `static/admin/kb.html`（新） | 单文件管理页（原生 JS） |
| `src/agentlab/rag/corpus.py`（改） | 新增 `load_corpus_dirs(dirs)`：目录内重名报错，跨目录后者覆盖前者 |
| `src/agentlab/rag/ingest.py`（改） | 摄取基于合并后的文档列表；启动扫描 `[corpus, uploads]` |
| `src/agentlab/services.py` / `config.py`（改） | 双目录摄取；新增 `ADMIN_TOKEN`、`UPLOAD_DIR`、`MAX_UPLOAD_BYTES` |
| `docker-compose.yml`（改） | app 挂载 `./data/uploads:/app/data/uploads` |
| `Dockerfile`（改） | `COPY static ./static` |

### 数据与合并规则

- 源文档：`data/corpus/`（内置，只读，git 管理）+ `data/uploads/`（上传，可增删改）
- 合并：按 `doc_id` 建索引，uploads 覆盖 corpus；**同一目录内重复 `doc_id` 仍报错**
- 启动摄取：合并列表 → 内容哈希增量入库；不在合并结果中的文档从库中删除
- 编辑内置文档：生成 uploads 覆盖版本，不修改 git 文件；删除覆盖后回退内置并重建索引
- 删除：仅允许 uploads 源；内置且无覆盖返回 403

### 并发与原子性

- 上传/编辑/删除/启动摄取共用 `asyncio.Lock` 串行化；检索只读不加锁
- 写文件：临时文件 + `os.replace` 原子替换，任何异常不留半成品
- 先完成切块与向量化（可能失败），再写源文件，再 `store.replace_doc`；入库失败返回 502 并在日志注明"源文件已保存，重启自动重建"

## 接口契约

鉴权：所有 `/api/kb/*` 需 `X-Admin-Token`（常量时间比较）。未配置 `ADMIN_TOKEN` → 503；错误 → 401。

| 方法 & 路径 | 请求 | 响应 |
|---|---|---|
| `GET /api/kb/docs` | — | `{"docs":[{"doc_id","title","chunks","source","updated_at"}]}` |
| `GET /api/kb/docs/{doc_id}` | — | `{"doc_id","title","body","source"}`（body 不含 frontmatter） |
| `POST /api/kb/docs` | multipart `file`（.md ≤ 2MB），可选 `?overwrite=true` | `201 {"doc_id","title","chunks","source":"uploads"}`；已存在未确认 → 409 |
| `PUT /api/kb/docs/{doc_id}` | `{"body":"..."}` | `200 {"doc_id","chunks","source":"uploads"}`；重建 frontmatter，保留原元数据 |
| `DELETE /api/kb/docs/{doc_id}` | — | `200 {"result":"deleted_override"}` 或 `{"result":"reverted_to_builtin"}`；内置无覆盖 → 403 |
| `POST /api/kb/search` | `{"query","top_k"?,"threshold"?}` | `{"results":[{"doc_id","chunk_index","title","heading","score","content"}],"effective":{...}}` |

约束：

- `doc_id`：`^[a-z0-9][a-z0-9._-]{0,63}$`；上传缺省取文件名
- `updated_at`：取对应源文件 mtime（ISO 8601）；无源文件时为 `null`
- `top_k` 1–20，`threshold` 0–1，缺省沿用 `.env` 配置
- 检索结果 `content` 截断 200 字；完整正文走 `GET /docs/{doc_id}`
- 错误统一 `{"detail": "中文说明"}`

## 管理页

单文件 `/admin/kb`（同源托管，零构建）：

- Token 首次输入存 `sessionStorage`；401 清空并要求重输；503 提示功能未启用
- 上传：文件选择/拖拽；409 弹确认后带 `overwrite=true` 重传
- 列表：doc_id、标题、chunks、来源（内置/上传）、更新时间；操作 [查看/编辑] [删除]（内置无覆盖时不显示删除）
- 编辑：`<textarea>` 加载正文，保存走 PUT；内置文档保存后来源显示"上传（覆盖）"
- 删除：二次确认；`reverted_to_builtin` 时提示已恢复内置
- 检索预览：问题输入、top_k 数字框、阈值滑杆、结果按分数降序展示
- 安全：内容一律 `textContent` 渲染，token 不进 localStorage

## 错误处理

| 场景 | 状态码 |
|---|---|
| token 未配置 / 错误 | 503 / 401 |
| 重名未确认 | 409 |
| doc_id 非法、frontmatter 缺失、正文为空 | 400 |
| 文件超限 | 413 |
| 删除内置无覆盖 | 403 |
| 文档不存在 | 404 |
| embedding/入库失败 | 502 |

## 测试

全部使用 fake embeddings + 内存/临时目录，不依赖 DashScope：

- `tests/test_kb.py`（新）：上传/列表/编辑/覆盖/删除回退、跨目录优先级、目录内重名、非法输入、原子写
- `tests/test_kb_api.py`（新）：鉴权 503/401/200、409→overwrite、PUT/GET、DELETE 403/200、search 参数钳制
- 更新：`test_corpus.py`、`test_ingest.py`、`test_config.py`
- 回归命令：`uv run ruff check .` 与 `uv run pytest -q -m "not integration"`

## 配置与部署

- `.env.example` 新增：
  - `ADMIN_TOKEN=`（`openssl rand -hex 32` 生成）
  - `UPLOAD_DIR=data/uploads`
  - `MAX_UPLOAD_BYTES=2097152`
- `.gitignore` 增加 `data/uploads/`；启动时自动创建目录
- `Dockerfile` 增加 `COPY static ./static`
- `docker-compose.yml` app 增加 `./data/uploads:/app/data/uploads`
- README 增加"知识库管理"使用说明

## 验收

1. 静态检查与全部非集成测试通过
2. 本地 mock 模式端到端：token 输入 → 上传 → 列表 → 编辑 → 检索预览 → 删除
3. 可选真实环境：上传后 `kb_chunks` 行数变化正确；重启后上传文档仍在
4. 构建镜像后 `static/admin/kb.html` 存在且可访问
