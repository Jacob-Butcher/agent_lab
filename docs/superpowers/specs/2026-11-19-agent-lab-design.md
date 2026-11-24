# Agent Lab 设计文档

- 状态：设计已确认（Design Approved）
- 日期：2026-11-19
- 项目路径：`/Users/geigeiguo/code/agent-lab`
- 目标：在 1–2 周内交付一个可运行、可观测、可评估的 Python AI Agent 实训项目

---

## 1. 背景

原始参考图描述的是一套 Spring AI Alibaba + StateGraph 的企业级 Agent 架构：状态图编排、Redis 短期记忆、PostgreSQL + pgvector 知识库、MCP 工具调用、OpenTelemetry + Micrometer 可观测性，以及工具权限控制。

经过技术选型对比，本项目改用 Python 实现，但保留原架构的核心意图：

- 用 **LangGraph** 替代 Spring AI Alibaba Graph，实现真正的状态图（条件边、循环、检查点）；
- 用 **FastAPI + SSE** 提供流式对话入口；
- 用 **Postgres + pgvector** 承载 RAG 知识库；
- 用 **MCP** 把工具放到独立进程，演示标准化工具调用；
- 用 **OpenTelemetry + Prometheus** 覆盖链路与指标；
- 用三层评估（检索、工具/权限、端到端）证明系统不是“只会聊天”。

语言切换是有意为之：Python 版的 StateGraph、MCP、RAG 评估生态更成熟，能在有限工期内做出完整闭环。代价是不再证明 Java/Spring 能力，这一点已在选型阶段确认。

---

## 2. 目标与非目标

### 2.1 目标

| 编号 | 目标 |
|---|---|
| G1 | 一条请求能完整走通：规划 → 检索/工具 → 回答，且带引用 |
| G2 | StateGraph 具备条件边、循环、终止守卫和检查点恢复 |
| G3 | 工具通过独立 MCP 服务暴露，权限在服务端强制执行 |
| G4 | 一次请求可在 Jaeger 中看到跨两个进程的完整链路，并暴露 Prometheus 指标 |
| G5 | 产出可复现的三层评估报告：检索、工具/权限、端到端 |

### 2.2 非目标（一期明确不做）

- 多 Agent 协作 / 角色互审
- 跨会话长期记忆（用户画像、事实抽取）
- 人工审批中断（LangGraph `interrupt`）
- 向量库替换为 Milvus / Elasticsearch
- Kubernetes、灰度发布、生产级认证与多租户
- 将 MCP 服务暴露到公网
- 前端框架（只用静态页面）

---

## 3. 关键决策（ADR 摘要）

| 编号 | 决策 | 备选 | 理由 |
|---|---|---|---|
| D1 | Python 3.12 + LangGraph 1.2 | Java 21 + Spring AI Alibaba | 用户确认；状态图、MCP、RAG 评估生态更成熟 |
| D2 | 主应用 + 独立 MCP 工具服务（双进程） | 单体内嵌工具 | 演示进程边界、标准化工具与跨进程链路 |
| D3 | MCP 走路径 B：`mcp 1.30.0` + `langchain-mcp-adapters 0.3.2` | `mcp 2.3` + `langchain.mcp`（beta） | 避开 beta API；路径已验证可用 |
| D4 | 检查点优先 Redis，失败降级 Postgres | 只用 Postgres | 保留原图的 Redis 短期记忆语义；降级路径明确 |
| D5 | 评估分三层：检索、工具/权限、端到端 | 只评 RAG | 用户选择；Agent 能力不能只用召回率衡量 |
| D6 | 演示认证用请求头 `X-User-Id` / `X-Role` | Spring Security / OAuth2 | 控制工期；权限判定仍在服务端强制执行 |

---

## 4. 技术栈与版本

以下版本为 2026-11-19 在 PyPI 核验的版本。最终补丁版本由 `uv lock` 固定并提交 `uv.lock`。

| 组件 | 版本 | 说明 |
|---|---|---|
| Python | 3.12.15 | 本机已安装；3.14 暂不采用 |
| uv | 0.13.5 | 本机已安装 |
| LangGraph | 1.2.22 | 状态图、检查点、流式 |
| langgraph-checkpoint-redis | 0.6.0 | 首选检查点后端 |
| langgraph-checkpoint-postgres | 3.2.1 | 降级检查点后端 |
| LangChain | 1.5.0 | `langchain-core` 解析为 1.8.3 |
| langchain-mcp-adapters | 0.3.2 | 约束 `mcp>=1.24,<2.0` |
| MCP Python SDK | 1.30.0 | 1.x 最新版；提供服务端 `FastMCP` 与客户端 |
| langchain-postgres | 0.0.19 | PGVector 集成 |
| FastAPI | 0.163.2 | Web / SSE |
| sse-starlette | 3.7.0 | SSE 响应 |
| pydantic-settings | 2.16.3 | 配置与环境变量 |
| OpenTelemetry SDK | 1.45.2 | 链路；配套 OTLP HTTP exporter |
| Prometheus client | 随 `uv.lock` | 指标暴露 |
| RAGAS | 0.4.4 | 检索层辅助评估 |
| pytest / pytest-asyncio | 随 `uv.lock` | 单测与集成测试 |

### 4.1 依赖约束

- `langchain-mcp-adapters 0.3.2` 明确要求 `mcp<2.0.0`，因此 **不得** 同时安装 `mcp 2.x`。
- 不导入 `langchain.mcp`（该模块为 beta 且需要额外的 `fastmcp` 包）。
- 所有依赖精确锁版本；升级必须单独走一次兼容性验证并更新本文档。

### 4.2 模型接入

- 通过 DashScope 的 **OpenAI 兼容端点** 调用：
  - Chat：`qwen-plus`
  - Embedding：`text-embedding-v4`（北京区域）或 `text-embedding-v3`（国际区域），维度 `1024` 可配置
- API Key 与区域强绑定：Key 与 `base_url` 必须同区域。
- 业务代码只依赖 LangChain 的 `BaseChatModel` / `Embeddings` 抽象；provider 构造集中在 `config.py`，切换 provider 不改节点代码。

---

## 5. 架构与运行时

### 5.1 拓扑

```
Browser
  │ SSE
  ▼
agentlab:8080 (FastAPI)
  ├─ LangGraph StateGraph
  ├─ DashScope (chat + embedding)
  ├─ PostgreSQL 17 + pgvector   (知识库 / 审计 / 幂等 / 可选检查点)
  ├─ Redis 8                    (LangGraph 检查点)
  └─ MCP client ── HTTP ──▶ mcp_server:8081 (FastMCP, streamable HTTP)
```

### 5.2 进程

| 进程 | 入口 | 端口 | 职责 |
|---|---|---|---|
| 主应用 | `uv run agentlab` | 8080 | API、图编排、RAG、权限、观测 |
| MCP 服务 | `uv run mcp-tools` | 8081 | 暴露订单/工单工具，校验调用方 Token |

两个进程共用同一个虚拟环境；MCP 服务不访问图状态，只接收工具参数并返回结构化结果。

### 5.3 运行 profile

| profile | 模型 | 存储 | 用途 |
|---|---|---|---|
| `local` | DashScope | 真实 PG + Redis | 联调与演示 |
| `mock` | 脚本化假模型 | `InMemoryVectorStore` + `MemorySaver` | 单测、路由/权限测试、CI |
| `eval` | DashScope | 真实 PG | 三层评估，按需运行 |

---

## 6. 目录结构

```
agent-lab/
├── pyproject.toml
├── uv.lock
├── .env.example
├── README.md
├── src/agentlab/
│   ├── config.py
│   ├── api/                  # FastAPI、SSE、管理接口
│   ├── graph/
│   │   ├── state.py          # AgentState、Plan、证据结构
│   │   ├── nodes.py          # 7 个节点
│   │   ├── routing.py        # 条件边与守卫
│   │   └── build.py          # StateGraph 编译、checkpointer
│   ├── memory/               # 检查点工厂、裁剪、摘要
│   ├── rag/                  # 切分、入库、检索、引用
│   ├── tools/
│   │   ├── local.py          # 本地工具
│   │   ├── mcp_client.py     # MultiServerMCPClient、interceptor
│   │   └── permissions.py    # 角色策略、审计、幂等
│   ├── observability/        # OTel、指标、日志
│   └── audit/
├── mcp_server/
│   ├── server.py             # FastMCP 服务
│   └── data.py               # 订单/工单演示数据
├── demo/                     # 静态页面
├── scripts/                  # dev-up、ingest、run_eval
├── eval/
│   ├── retrieval_qa.jsonl    # 25 条
│   ├── agent_scenarios.jsonl # 30 条
│   └── reports/              # 生成的报告
├── data/corpus/              # 30 篇虚构知识库 Markdown
├── tests/
└── docs/
    ├── design.md             # 指向本文件
    ├── eval-report.md
    ├── permission-matrix.md
    ├── adr/
    └── img/
```

---

## 7. 配置

### 7.1 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DASHSCOPE_API_KEY` | 无 | 必填；与区域匹配 |
| `DASHSCOPE_BASE_URL` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 国际区改用 `dashscope-intl` |
| `CHAT_MODEL` | `qwen-plus` | |
| `EMBEDDING_MODEL` | `text-embedding-v4` | |
| `EMBEDDING_DIM` | `1024` | 必须与 pgvector 列维度一致 |
| `POSTGRES_DSN` | `postgresql://localhost/agentlab` | |
| `REDIS_URL` | `redis://localhost:6379/0` | |
| `CHECKPOINTER` | `redis` | `redis` 或 `postgres` |
| `MCP_SERVER_URL` | `http://127.0.0.1:8081/mcp` | streamable HTTP |
| `MCP_AUTH_TOKEN` | 无 | 演示用共享 Token |
| `AGENT_MAX_ITERATIONS` | `4` | plan 次数上限 |
| `AGENT_MAX_TOOL_CALLS` | `3` | 单请求工具调用上限 |
| `AGENT_MAX_TOKENS` | `20000` | 单请求 token 预算 |
| `AGENT_MAX_SECONDS` | `60` | 单请求超时 |
| `RAG_TOP_K` | `5` | |
| `RAG_SCORE_THRESHOLD` | `0.30` | |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4318` | OTLP HTTP |
| `OTEL_SERVICE_NAME` | `agentlab` | |
| `EVAL_MAX_SCENARIOS` | `30` | 评估上限 |
| `EVAL_MAX_TOKENS` | `200000` | 评估总预算 |

### 7.2 启动校验

启动时执行，任一失败即拒绝启动：

1. `DASHSCOPE_API_KEY` 存在，且 chat 与 embedding 各做一次最小调用探测；
2. pgvector 扩展存在，`kb_chunks.embedding` 维度等于 `EMBEDDING_DIM`；
3. 若 `CHECKPOINTER=redis`，验证 Redis 具备 JSON 与 Search 模块；不具备则按 D4 降级为 Postgres 并记录警告；
4. `audit_events`、`tool_idempotency` 表存在（由迁移脚本创建）；
5. MCP 服务健康检查通过；失败时主应用仍可启动，但 MCP 工具标记为不可用。

---

## 8. StateGraph 设计

### 8.1 状态结构

```text
AgentState:
  # 输入
  query: str
  user_id: str
  role: guest | agent | admin
  session_id: str
  trace_id: str

  # 会话（跨轮由 checkpointer 恢复）
  messages: Annotated[list[Message], add_messages]
  summary: str | None

  # 规划与预算
  plan: Plan | None
  iterations: int
  tool_calls: int
  tokens_used: int

  # 证据（追加式）
  retrieved: Annotated[list[RetrievedChunk], operator.add]
  tool_results: Annotated[list[ToolResult], operator.add]

  # 输出
  answer: str | None
  citations: Annotated[list[Citation], operator.add]
  error: str | None

  # 审计（追加式）
  audit: Annotated[list[AuditEvent], operator.add]
```

`Plan` 使用 Pydantic 模型做结构化输出：

```text
Plan:
  action: retrieve | tool | answer
  query: str | None          # action=retrieve 时的检索改写
  tool_name: str | None
  tool_args: dict | None
  rationale: str
```

`RetrievedChunk`：`chunk_id, doc_id, title, heading, text, score, access_level`。

`ToolResult`：`tool, ok, output, error, latency_ms, decision`。

`Citation`：`doc_id, chunk_id, title, snippet`。

### 8.2 节点

| 节点 | 职责 | 关键约束 |
|---|---|---|
| `normalize` | 校验入参、解析角色、裁剪历史、初始化预算与 trace | 超 token 时先裁剪最旧消息；保留系统提示与最近一轮 |
| `plan` | 结构化规划 | 只把当前角色可用的工具放进 prompt；解析失败转 `answer` |
| `retrieve` | 向量检索并生成引用 | 按角色过滤 `access_level`；空结果不报错 |
| `execute` | 权限判定并执行工具 | 权限在调用前判定；返回结构化错误而非抛异常 |
| `respond` | 组装并流式输出回答 | 有证据必须带引用；无证据需声明 |
| `fallback` | 安全兜底 | 输出错误码与 trace_id，不生成未经验证的事实 |
| `persist` | 写审计、可选摘要 | 检查点由框架自动落盘，本节点只做业务侧持久化 |

### 8.3 边与循环

```text
START → normalize → plan
plan ─┬─ retrieve → plan
      ├─ execute  → plan
      ├─ answer   → respond
      └─ invalid/budget → fallback

respond → persist → END
fallback → persist → END
```

`retrieve` 与 `execute` 都回到 `plan`，由模型根据新证据决定下一步。这形成真正的状态图循环，而不是线性流水线。

### 8.4 守卫

| 守卫 | 默认 | 触发行为 |
|---|---|---|
| `MAX_ITERATIONS` | 4 | 强制 `answer`，不会无限规划 |
| `MAX_TOOL_CALLS` | 3 | 强制 `answer` |
| 单工具重试 | 1 | 重试后仍失败则本轮禁用该工具 |
| 循环检测 | 相同 `(action, tool_name, args_hash)` 连续出现 | 立即终止循环，转 `answer` |
| `MAX_TOKENS` | 20000 | `fallback` |
| `MAX_SECONDS` | 60 | `fallback` |
| 权限拒绝 | — | 不重试同一工具；把拒绝原因交给 `plan` 生成解释 |

### 8.5 检查点与恢复

- `thread_id = f"{user_id}:{session_id}"`。
- 首选 `RedisSaver`；Redis 缺少 JSON/Search 模块时降级 `PostgresSaver`，启动日志与 ADR 明确记录。
- 一期不使用 `interrupt`；恢复仅用于进程重启后的会话续跑。
- Redis 检查点 TTL 7 天；Postgres 检查点由清理脚本按天数删除。

### 8.6 流式事件

通过 LangGraph 的流式接口转发为 SSE，事件类型：

| 事件 | 负载 |
|---|---|
| `node_start` | node 名称、iteration |
| `token` | 增量文本 |
| `citation` | doc_id、标题、片段 |
| `done` | answer、citations、token 用量 |
| `error` | 错误码、trace_id、可展示信息 |

### 8.7 记忆裁剪

- 短期记忆由检查点承载，按 `thread_id` 隔离。
- `normalize` 按 token 预算裁剪历史；超过阈值时保留最近 N 轮与 `summary`。
- LLM 摘要为可选能力：仅在配置开启时调用，默认关闭，避免额外成本与延迟。
- 长期记忆（跨会话事实/偏好）一期不做。

---

## 9. RAG 设计

### 9.1 语料

- 30 篇虚构“售后知识库”Markdown，覆盖政策、退换货、发票、物流、保修。
- 每篇 front matter 含 `doc_id`、`title`、`access_level`（`public` / `internal` / `restricted`）、`version`。
- 语料完全自建，避免版权与隐私问题，保证评估可复现。

### 9.2 切分与元数据

- 先按 Markdown 标题切分，再用递归字符切分；目标 500 token，重叠 50。
- 切片元数据：`doc_id, title, heading, chunk_index, access_level, version, content_hash`。
- 入库按 `content_hash` 幂等；文档变更时删除该文档旧切片后重写。

### 9.3 存储

- 表 `kb_chunks`：`id, doc_id, chunk_index, content, metadata jsonb, embedding vector(1024)`。
- 索引：HNSW，`vector_cosine_ops`。
- 启动时校验列维度与 `EMBEDDING_DIM` 一致；不一致直接拒绝启动。

### 9.4 检索

- `top_k=5`，`score_threshold=0.30`，按角色映射允许的 `access_level` 过滤。
- 可选 MMR（`lambda=0.5`）提升多样性；默认关闭，配置开启。
- 上下文总量上限 3k token；超出按分数截断。
- 去重：同一 `doc_id + chunk_index` 只保留一次。

### 9.5 引用

- 回答必须包含 `[doc_id#chunk_index]` 形式的引用标记。
- `respond` 节点从 `retrieved` 生成 `citations`，通过 SSE `citation` 事件推给前端。
- 无检索证据且未调用工具时，回答必须显式声明“未在知识库中找到依据”。

### 9.6 入库命令

`uv run ingest --corpus data/corpus`：读取语料、切分、embedding、upsert；输出处理统计与失败文档列表。

---

## 10. 工具与权限

### 10.1 工具清单

| 工具 | 位置 | 类型 | 说明 |
|---|---|---|---|
| `calculate_refund` | 主应用本地 | 纯函数 | 对照用；不访问外部系统 |
| `query_order` | MCP 服务 | 读 | 按订单号查询状态 |
| `create_ticket` | MCP 服务 | 写 | 创建售后工单，带幂等键 |
| `cancel_order` | MCP 服务 | 高风险写 | 取消订单，仅 admin |

### 10.2 MCP 服务端

- 使用 `mcp.server.fastmcp.FastMCP`，streamable HTTP 传输，监听 8081。
- 启动时读取 `MCP_AUTH_TOKEN`；每个请求校验 `Authorization: Bearer <token>`。
- 工具返回结构化 JSON；错误通过结构化字段返回，不把异常文本直接透给模型。
- 服务端记录每次调用的工具名、参数哈希、调用方、耗时、结果状态。
- 演示数据保存在 `mcp_server/data.py`，进程内可变；不连接真实订单系统。

### 10.3 MCP 客户端

- 使用 `MultiServerMCPClient` 连接 streamable HTTP：
  - 连接名：`orders`
  - URL：`MCP_SERVER_URL`
  - Header：`Authorization: Bearer ${MCP_AUTH_TOKEN}`
- 通过 `get_tools()` 获取 LangChain 工具列表。
- 使用 **`tool_interceptors`** 统一挂载权限校验与 `tool.call` span；不在每个业务工具里重复实现。
- 连接失败时 MCP 工具标记为不可用，主应用继续提供本地工具与 RAG 能力。

### 10.4 权限矩阵

| 能力 | guest | agent | admin |
|---|---|---|---|
| 知识库 `public` | ✓ | ✓ | ✓ |
| 知识库 `internal` | ✗ | ✓ | ✓ |
| 知识库 `restricted` | ✗ | ✗ | ✓ |
| `calculate_refund` | ✗ | ✓ | ✓ |
| `query_order` | ✗ | ✓ | ✓ |
| `create_ticket` | ✗ | ✗ | ✓ |
| `cancel_order` | ✗ | ✗ | ✓ |

### 10.5 三层强制

1. **规划前过滤**：`plan` 只看到当前角色可用的工具与知识库范围。
2. **执行前校验**：`tool_interceptors` 校验角色、工具、参数策略；拒绝时返回结构化 `decision=denied`，不执行底层工具。
3. **MCP 服务端校验**：共享 Token + 调用方记录，防止绕过主应用直接调用。

参数策略示例：`order_id` 必须匹配 `^A[0-9]{4,}$`；退款金额不得超过订单金额；写工具必须带幂等键。

### 10.6 审计

- 表 `audit_events`：`ts, user_id, role, session_id, trace_id, tool, args_hash, decision, latency_ms, status`。
- 权限拒绝、工具失败、写操作成功都必须落库。
- 审计写入失败时，写工具**失败关闭**（拒绝执行）；读工具可继续并记录告警日志。

### 10.7 幂等

- 写工具幂等键：`hash(session_id, tool_name, canonical_json(args))`。
- 表 `tool_idempotency` 以幂等键为唯一约束；重复调用返回首次结果。
- 幂等记录保留 24 小时。

### 10.8 工具失败语义

| 情况 | 行为 |
|---|---|
| 权限拒绝 | 不执行；结果交给 `plan` 生成解释；审计 `denied` |
| 参数非法 | 不执行；返回校验错误；允许 `plan` 修正一次 |
| MCP 超时 | 重试 1 次；仍失败则本轮禁用该工具 |
| MCP 不可达 | 标记不可用；后续请求不再尝试，直到健康检查恢复 |
| 工具返回错误结构 | 视为失败，记录原始错误码，不把内部细节展示给用户 |

---

## 11. 可观测性

### 11.1 Span

| Span | 关键属性 |
|---|---|
| `graph.node` | `node`, `iteration`, `role`, `session_id` |
| `llm.chat` | `model`, `input_tokens`, `output_tokens`, `latency_ms` |
| `rag.retrieve` | `top_k`, `hits`, `max_score`, `access_levels` |
| `tool.call` | `tool.name`, `decision`, `status`, `latency_ms` |
| `mcp.tools.call`（服务端） | `tool.name`, `caller`, `status` |

### 11.2 跨进程传播

- 主应用通过 HTTPX 调用 MCP 服务；HTTP 请求头携带 W3C `traceparent`。
- MCP 服务端从请求头提取上下文并续接同一 trace。
- 验收标准：一次用户请求在 Jaeger 中同时出现主应用与 MCP 服务的 span，且 `trace_id` 相同。

### 11.3 指标

| 指标 | 类型 | 标签 |
|---|---|---|
| `agent_requests_total` | counter | `status`, `role` |
| `agent_node_duration_seconds` | histogram | `node` |
| `agent_tool_calls_total` | counter | `tool`, `decision`, `status` |
| `rag_empty_retrievals_total` | counter | — |
| `llm_tokens_total` | counter | `type`, `model` |
| `agent_loop_terminations_total` | counter | `reason` |

指标通过 `/metrics` 暴露给 Prometheus。

### 11.4 本地 UI 与日志

- 本地 Jaeger all-in-one 接收 OTLP HTTP（4318）；M0 验证安装方式。
- 若 Jaeger 安装失败，按顺序尝试：Grafana Tempo + Grafana（本地二进制）、Uptrace（单二进制）、OTel Collector + Jaeger；仍失败才退化到 OTLP console exporter + 结构化日志。链路 UI 截图是交付物硬要求，M0 必须选定一条可运行路径。
- 日志为 JSON：`ts, level, trace_id, session_id, user_id, role, event, fields`；不记录完整工具参数，只记哈希。

---

## 12. 评估方案（三层）

### 12.1 数据集

| 文件 | 数量 | 内容 |
|---|---|---|
| `eval/retrieval_qa.jsonl` | 25 | `question, reference_answer, gold_doc_ids, role` |
| `eval/agent_scenarios.jsonl` | 30 | `id, role, input, expect{tools, forbidden_tools, permission, must_cite, answer_contains}` |

场景覆盖：guest / agent / admin 各角色；允许与拒绝；读工具与写工具；无工具纯问答；需要多轮检索；越权尝试；循环诱导（要求模型反复调用）。

### 12.2 指标定义

**检索层**

- `Recall@5`：对每个问题，金标文档集合与 Top-5 检索结果的交集占金标集合的比例，取平均。
- `MRR@10`：第一个金标文档排名倒数的平均。
- `Hit@1`：Top-1 命中至少一个金标文档的问题占比。
- RAGAS（可选）：`context_precision`、`context_recall`；LLM judge 使用同一 DashScope 模型。

**工具/权限层**

- `Tool Selection Accuracy`：期望工具集合与实际调用集合完全一致（含顺序不敏感）的场景占比。
- `Argument Accuracy`：需要工具的场景中，关键参数（如 `order_id`）正确的占比。
- `Forbidden Tool Call Rate`：出现任一 `forbidden_tools` 执行的场景占比，**硬门槛为 0**。
- `Permission Denial Correctness`：拒绝场景中“未执行工具 + 返回拒绝说明”的占比，**硬门槛为 100%**。
- `Duplicate Write Rate`：同一幂等键产生多次副作用的比例，**硬门槛为 0**。

**端到端层**

- `Task Success Rate`：`answer_contains`、`must_cite`、权限结果三项断言全部通过的场景占比；另做 20% 人工抽检修正。
- `Citation Coverage`：有证据回答中带引用的比例。
- `Convergence Rate`：在预算内正常走到 `respond`（非 fallback/守卫触发）的比例。
- `Fallback Rate`：fallback 终止占比。
- `P95 Latency`、平均 token 用量、评估总费用。

### 12.3 两套执行器

| 执行器 | 规划器 | 覆盖范围 | 运行要求 |
|---|---|---|---|
| `tests/` | 脚本化假 LLM | 路由、权限、守卫、幂等、引用组装 | 100% 通过，进 CI |
| `eval/` | DashScope 真模型 | 模型规划行为、工具选择、端到端成功率 | 按需运行，结果写报告 |

假规划器负责证明“逻辑正确”；真模型负责测量“模型表现”。两者结果不得混在同一张表里下结论。

### 12.4 判定

| 指标 | 判定 |
|---|---|
| Forbidden Tool Call Rate | 必须 0 |
| Permission Denial Correctness | 必须 100% |
| Duplicate Write Rate | 必须 0 |
| Recall@5 | 目标 ≥ 0.80，记录基线 |
| Convergence Rate | 目标 ≥ 95% |
| Task Success Rate | 诊断目标 ≥ 80% |

未达目标不阻塞交付，但必须在报告中列出失败案例与原因。

### 12.5 成本控制

- LLM 响应按 prompt 哈希缓存，重复评估不重复付费。
- `EVAL_MAX_SCENARIOS` 与 `EVAL_MAX_TOKENS` 限制单次评估规模。
- 报告中记录实际调用次数、token 与估算费用。
- RAGAS 只对检索层抽样运行，不参与工具/端到端评估。

### 12.6 报告结构

`docs/eval-report.md` 固定三章：

1. 检索层：数据集版本、配置、Recall@5 / MRR@10 / Hit@1、失败案例。
2. 工具/权限层：场景矩阵、三项硬门槛结果、工具选择与参数失败案例。
3. 端到端层：成功率、引用覆盖、收敛率、fallback、延迟与费用、人工抽检结论。

报告必须写明“30/25 条为小样本诊断，不构成 benchmark”。

---

## 13. 错误处理与降级

| 失败 | 处理 |
|---|---|
| LLM 超时 | 重试 2 次（指数退避）；仍失败转 `fallback` |
| 规划输出无法解析 | 转 `answer`，请用户澄清；不重试同一提示 |
| Embedding 调用失败 | 检索返回空证据并标记降级；回答声明无依据 |
| PG 不可用 | 读路径失败；写审计失败时写工具失败关闭 |
| Redis 不可用 | 检查点降级 Postgres；启动日志告警 |
| MCP 超时/不可达 | 重试/禁用工具；主应用其余能力继续 |
| 预算耗尽 | `fallback`，附 trace_id 与已获得的部分结论 |
| 审计写入失败 | 写工具拒绝执行；读工具继续并告警 |

---

## 14. 测试策略

| 层级 | 内容 | 依赖 |
|---|---|---|
| 单元 | 节点逻辑、路由表、守卫、裁剪、引用组装、参数校验 | 假 LLM / 假 retriever / 假工具 |
| 权限 | 权限矩阵逐格参数化；拒绝不产生副作用；审计字段完整 | 进程内 MCP 服务或假工具 |
| 图集成 | `MemorySaver` + `InMemoryVectorStore` 跑完整图；验证循环、终止、恢复 | 无外部服务 |
| API | SSE 事件顺序与负载；错误码；角色头解析 | `httpx.AsyncClient` |
| MCP | `FastMCP` 进程内服务 + `MultiServerMCPClient`；schema、错误、超时、鉴权 | 本地进程 |
| 可观测 | `InMemorySpanExporter` 断言 span 与属性；指标注册表断言 | 无 |
| 评估 | 三层数据集；真实 DashScope | 标记 `eval`，不进默认 CI |

pytest 标记：`unit`、`integration`、`mcp`、`observability`、`eval`。默认命令：`pytest -m "not eval"`。

每个节点、每个权限矩阵单元、每个守卫分支都必须有测试用例。

---

## 15. 交付物

1. 可运行代码（双进程、uv 管理、`uv.lock` 提交）
2. `docs/design.md`（本文件）
3. `docs/eval-report.md` + `eval/*.jsonl` + 评估脚本
4. `docs/permission-matrix.md` + 对应的参数化测试
5. `docs/img/`：Jaeger 跨进程链路截图、Prometheus 指标截图
6. `README.md`：环境安装、启动、评估、故障排查
7. `.env.example`
8. `docs/adr/`：D1–D6 决策记录
9. 静态演示页：角色切换、流式回答、引用展示

---

## 16. 里程碑与验收标准

| 阶段 | 内容 | 估时 | 验收 |
|---|---|---|---|
| M0 | 环境预检与依赖锁 | 0.5d | PG+pgvector、Redis 模块、Jaeger、DashScope 探测、MCP 路径 B smoke test 全部通过 |
| M1 | 骨架、配置、SSE、mock provider | 1d | `uv run agentlab` 启动；mock 模式可流式返回；启动校验生效 |
| M2 | 语料、入库、检索、引用 | 1.5d | 30 篇语料入库；检索返回引用；维度校验生效 |
| M3 | StateGraph 节点、路由、守卫、检查点 | 1.5d | 假模型下整图跑通；守卫与循环测试通过；Redis 检查点或降级生效 |
| M4 | 本地 + MCP 工具、权限、审计、幂等 | 2d | 权限矩阵逐格通过；越权调用为 0；审计与幂等测试通过 |
| M5 | OTel、指标、跨进程传播 | 1d | 一次请求在 Jaeger 中跨两个进程可见；`/metrics` 有数据 |
| M6 | 评估、报告、演示页、文档 | 2d | 三层报告生成；README 可复现；演示页可用 |

合计约 **9.5 个工作日**。

---

## 17. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| MCP 1.x 后续淘汰 | 适配层返工 | 精确锁版本；逻辑隔离在 `mcp_client.py`；升级单独验证 |
| Redis 缺 JSON/Search 模块 | 检查点不可用 | 自动降级 PostgresSaver；ADR 记录 |
| DashScope Key 区域不匹配 | 全部模型调用失败 | 启动探测；`.env.example` 标注区域 |
| embedding 维度不一致 | 检索静默失败 | 启动校验列维度，不一致拒绝启动 |
| RAGAS judge 中文不稳 | 评估结论失真 | 确定性指标为主；20% 人工抽检；报告标注样本量 |
| LangGraph 节点缺自动 span | 链路不完整 | 手动 span + InMemory exporter 断言 |
| 版本漂移 | 构建不可复现 | 精确锁版本 + 提交 `uv.lock` |
| 无 Docker | 中间件安装受阻 | Homebrew 原生安装；脚本做预检 |
| 评估费用超预期 | 成本失控 | 缓存、场景/ token 上限、按需运行 |
| MCP 工具错误被当成功 | 指标失真 | 结构化错误字段 + span 显式标记失败 |

---

## 18. 假设

1. 用户提供与 `DASHSCOPE_BASE_URL` 同区域的 `DASHSCOPE_API_KEY`。
2. 本机允许通过 Homebrew 安装 PostgreSQL 17、pgvector、Redis，以及 Jaeger 运行方式。
3. 8080、8081、5432、6379、4318 端口未被占用。
4. 运行期间可访问 PyPI 与 DashScope。
5. 演示为单用户/少量用户场景，请求头认证不作为生产安全方案。

以上任一假设不成立，在 M0 阶段暴露并调整，不进入后续里程碑。

---

## 19. 后续扩展（不在本期）

- LangGraph `interrupt` 人工审批写操作
- 跨会话长期记忆（LangGraph Store + 摘要/事实抽取）
- 多 Agent 协作与评审节点
- MCP 网关（鉴权、限流、审计）
- 向量库替换与混合检索（BM25 + 向量）
- 容器化与 CI/CD

---

## 20. 附录：计划中的运行命令

```bash
# 中间件（Homebrew）
brew install postgresql@17 pgvector redis
brew services start postgresql@17
brew services start redis
createdb agentlab
psql agentlab -c 'CREATE EXTENSION IF NOT EXISTS vector;'

# 依赖与应用
uv sync
uv run migrate                 # 建表：kb_chunks / audit_events / tool_idempotency
uv run ingest --corpus data/corpus
uv run mcp-tools
uv run agentlab

# 测试与评估
uv run pytest -m "not eval"
uv run python scripts/run_eval.py --profile eval
```

这些命令是设计与实现之间的接口约定；具体参数在实现计划中细化。
