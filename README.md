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
docker compose up -d --build
```

3. 检查：

```bash
docker compose ps
curl -s localhost:8080/health
docker compose logs -f app
```

4. 打开 `http://<服务器>:8080`。

首次启动会自动建表并增量入库，日志会显示 `added/changed/skipped` 统计。

> 区域：默认 `DASHSCOPE_BASE_URL` 为中国北京区域。使用国际区 Key 时请改为
> `https://dashscope-intl.aliyuncs.com/compatible-mode/v1`，并把 `EMBEDDING_MODEL` 改为 `text-embedding-v3`。
> 若修改 `POSTGRES_PASSWORD`，请同步修改 `POSTGRES_DSN`。

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

## 验收清单（服务器）

- [ ] `docker compose up -d --build` 后 app/db/redis 均正常
- [ ] `curl localhost:8080/health` 返回 200
- [ ] 页面能流式回答，引用卡片出现
- [ ] 同一会话第二轮能引用上一轮内容
- [ ] 重启 app 后会话历史仍在
- [ ] 重启后不重复入库，日志出现 skipped
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
