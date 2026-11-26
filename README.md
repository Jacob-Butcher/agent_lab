# Agent Lab 智能客服

星选商城售后智能客服 MVP：FastAPI + LangGraph + pgvector + Redis，支持流式回答、知识库引用与会话记忆。

## 架构

```
浏览器 → FastAPI(SSE) → LangGraph(normalize → retrieve → respond)
                              ├─ DashScope（chat + embedding）
                              ├─ PostgreSQL + pgvector（知识库）
                              └─ Redis（会话记忆）
```

## 本地开发（无 Docker、无外部服务）

```bash
uv sync
MODEL_PROVIDER=mock MEMORY_BACKEND=memory uv run uvicorn agentlab.main:app --reload --port 8080
```

打开 http://localhost:8080 。mock 模式只验证链路，回答是模拟文本，检索质量不代表真实效果。

## 服务器部署

1. 复制环境变量并填写 DashScope Key（Key 必须与 `DASHSCOPE_BASE_URL` 同区域）：

```bash
cp .env.example .env
vi .env
```

2. 构建并启动：

```bash
mkdir -p data/uploads
sudo chown -R 10001:10001 data/uploads
docker compose up -d --build
```

3. 检查：

```bash
docker compose ps
curl -s localhost:8081/health
docker compose logs -f app
```

4. 打开 `http://<服务器>:8081`（compose 将容器 8080 映射到宿主机 8081）。

首次启动会自动建表并增量入库。

> 区域：默认 `DASHSCOPE_BASE_URL` 为中国北京区域。使用国际区 Key 时请改为
> `https://dashscope-intl.aliyuncs.com/compatible-mode/v1`，并把 `EMBEDDING_MODEL` 改为 `text-embedding-v3`。
> 若修改 `POSTGRES_PASSWORD`，请同步修改 `POSTGRES_DSN`。

## 知识库管理

1. 在 `.env` 设置 `ADMIN_TOKEN`（用 `openssl rand -hex 32` 生成；建议只用 ASCII/十六进制字符）

> 修改 `.env` 中任一变量后需重新创建容器生效：
> `docker compose up -d`（或 `docker compose up -d --force-recreate app`）。
> `docker compose restart` 不会重新读取 `env_file`。

2. 打开 `http://<服务器>:8081/admin/kb`，首次进入输入 Token
3. 支持上传 `.md` / `.txt` / `.pdf`（文字版）/ `.docx` / `.pptx`；非 md 文档会先解析为规范化 Markdown 再入库
4. 页/幻灯片编号会保留在引用里；DOCX/PPTX 文档内图片会用 `qwen-vl-ocr` 提取文字（`IMAGE_OCR_ENABLED` 可关闭；PDF 内嵌图片暂不提取）
5. 可查看/编辑正文、删除覆盖版本、做检索预览（看 score 调 `RAG_TOP_K` / `RAG_SCORE_THRESHOLD`）

上传时可填可选 `doc_id`（小写字母/数字/点/下划线/短横线，≤64 字符）；留空自动生成「格式-内容哈希」。`.md` 文件以 frontmatter 的 `doc_id` 为准。

上传内容保存在 `data/uploads/`（compose 已挂载）。内置 `data/corpus/` 文档在页面上只读，
编辑后会在 `data/uploads/` 生成同名覆盖版本；删除覆盖版本会自动恢复内置内容。

使用自带 compose 时 `UPLOAD_DIR` 必须保持 `data/uploads`，与挂载路径一致。

非 md 文档的原始文件与图片分别保存在 `$UPLOAD_DIR/.raw/`、`$UPLOAD_DIR/.assets/`（默认 `data/uploads`），删除文档时会一并清理。
扫描版 PDF 暂不支持；`.doc`/`.ppt` 旧格式与 xlsx 暂不支持。只含图片的 DOCX/PPTX 需要开启 `IMAGE_OCR_ENABLED`（且配置 DashScope Key、非 mock）才能入库。

Linux 服务器需在上线前保证 `data/uploads/` 对容器用户（UID 10001）可写（见服务器部署第 2 步）；
SELinux 主机还需为 bind mount 加 `:z`（如 `./data/uploads:/app/data/uploads:z`）。

> 安全提示：未配置 HTTPS 时 Token 可能被网络嗅探；建议用 Caddy/Nginx 反代并启用 TLS。
> 同时建议在反代层限制请求体大小（如 `client_max_body_size 60m`），因为上传接口在鉴权前会先解析 multipart 请求体。

## 配置说明

| 变量 | 说明 |
|---|---|
| `MODEL_PROVIDER` | `dashscope` 或 `mock` |
| `DASHSCOPE_API_KEY` | DashScope Key，区域需与 base URL 一致 |
| `EMBEDDING_DIM` | 必须与知识库向量维度一致，默认 1024 |
| `POSTGRES_DSN` / `REDIS_URL` | compose 内部地址 |
| `MEMORY_BACKEND` | `redis` 或 `memory` |
| `RAG_TOP_K` / `RAG_SCORE_THRESHOLD` | 检索数量与相似度阈值 |
| `MAX_HISTORY_MESSAGES` | 传给模型的最近消息数 |
| `ADMIN_TOKEN` | 知识库管理页令牌，留空则禁用管理接口（503） |
| `UPLOAD_DIR` | 上传文档目录（自带 compose 下须为 `data/uploads`） |
| `MAX_UPLOAD_BYTES` | 单次上传/编辑的最大字节数，默认 50MB |
| `MAX_DOC_PAGES` | PDF 页数 / PPT 幻灯片数上限，默认 100 |
| `MAX_DOC_CHARS` | 解析后正文最大字符数，默认 200 万 |
| `IMAGE_OCR_ENABLED` / `OCR_MODEL` | 图片文字识别开关与模型（mock 模式或未配置 DASHSCOPE_API_KEY 时自动关闭） |
| `MAX_ZIP_UNCOMPRESSED` / `MAX_ZIP_ENTRIES` | DOCX/PPTX 解压限制（防 zip bomb） |

## 验收清单（服务器）

- [ ] `docker compose up -d --build` 后 app/db/redis 均正常
- [ ] `curl localhost:8081/health` 返回 200
- [ ] 页面能流式回答，引用卡片出现
- [ ] 同一会话第二轮能引用上一轮内容
- [ ] 重启 app 后会话历史仍在
- [ ] 重启后不重复入库（内容哈希去重）
- [ ] 上传 txt/pdf/docx/pptx 后能在列表看到，检索结果带页/幻灯片编号（pdf/pptx）
- [ ] `docker compose logs app` 无未处理异常

## 测试

```bash
uv run pytest -q
uv run ruff check .
```

## 故障排查

| 现象 | 排查 |
|---|---|
| 启动失败提示 API Key | `.env` 是否填写、区域是否匹配 |
| 启动失败提示维度 | `EMBEDDING_DIM` 与知识库向量维度是否一致 |
| 回答不流式 | 反代是否缓冲；响应已设置 `X-Accel-Buffering: no` |
| 检索无结果 | 查看启动入库日志；确认语料存在且 embedding 成功 |
| Redis 连接失败 | `docker compose ps` 查看 redis 健康状态 |
