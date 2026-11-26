# Agent Lab 多格式知识库入库（P1）设计

日期：2026-11-26
状态：已评审待实现
前置：`2026-11-26-kb-admin-design.md`（KB 管理页与接口）

## 背景与目标

当前知识库只接受 `.md`。实际待入库资料包含 PDF、Word、PPT、TXT，且文档内常有文字截图。

目标：

- 支持 `.txt` / `.pdf`（文字版）/ `.docx` / `.pptx` 上传
- 所有格式统一转成**规范化 Markdown**，复用现有切块、embedding、pgvector 检索链路
- 页/幻灯片号保留为标题，检索引用可追溯
- 文档内图片用 DashScope `qwen-vl-ocr` 提取文字，失败不影响整体入库
- 保持部署简单：无新增服务、无异步任务队列

非目标（P1 明确不做）：

- 扫描版 PDF OCR；`.doc` / `.ppt` 旧格式；xlsx
- 解析进度条/后台任务队列（同步解析，一次几份文件）
- 图表视觉描述、多模态 embedding、图片引用展示
- PDF 内嵌图片提取（与"扫描件不做"保持一致）

## 选型与依赖

| 用途 | 库/服务 | 许可/备注 |
|---|---|---|
| PDF 文字与表格 | `pdfplumber` | MIT；**不用 PyMuPDF（AGPL）** |
| DOCX | `python-docx` | MIT |
| PPTX | `python-pptx` | MIT |
| 文件魔数校验 | `filetype` | MIT；docx/pptx 需再检查 zip 内 `word/` 或 `ppt/` 目录 |
| TXT 编码探测 | `charset-normalizer` | MIT，显式声明依赖 |
| 图片尺寸/去重 | `Pillow` | HPND（宽松） |
| 图片 OCR | DashScope `qwen-vl-ocr` | 复用现有 Key；走 OpenAI 兼容接口 + base64 data URL；失败可降级到 `qwen-vl-plus`（`OCR_MODEL` 可配） |
| 测试生成 PDF | `reportlab`（dev） | BSD 风格，仅测试使用 |

## 架构与数据流

```
POST /api/kb/docs (multipart)
  → 扩展名 + 魔数校验
  → .md：现有逻辑（跳过解析）
  → 其他格式：asyncio.to_thread 解析
        ParsedDocument(title, blocks=[text|table|page|image])
  → 图片块：IMAGE_OCR_ENABLED ? qwen-vl-ocr : 跳过（失败仅记日志）
  → 组装规范化 Markdown + frontmatter
  → 写 uploads/<doc_id>.md（规范化）
  → 原文件 uploads/.raw/<doc_id>.<ext>
  → 图片  uploads/.assets/<doc_id>/image-NN.<ext>
  → 复用 split_markdown → embedding → store.replace_doc
```

### 新增模块

```
src/agentlab/parsing/
├── __init__.py      # parse_document(filename, data, settings, ocr) -> ParsedDocument
├── base.py          # ParsedDocument / Block / ParseError / 公共清理函数
├── text.py          # txt（charset-normalizer）
├── pdf.py           # pdfplumber：按页文字、表格、页数限制
├── docx.py          # python-docx：标题/段落/表格/内联图片（按文档流顺序）
├── pptx.py          # python-pptx：每页文本/表格/图片
└── images.py        # 尺寸过滤、内容哈希去重、DashScope OCR 客户端（异步）
```

- 解析器**无副作用**：只返回 `ParsedDocument`，不写文件；由 `KBManager` 负责落盘与索引
- OCR 通过可注入的 `ImageOcr` 协议实现，测试使用假实现
- 写操作仍由现有 `asyncio.Lock` 串行化；解析（慢）在锁外执行，冲突检查与落盘/索引在锁内

### 规范化 Markdown 约定

frontmatter 固定包含：

```yaml
doc_id: pdf-3f9a2c71b8
title: 退款政策（2026版）
source_format: pdf
source_file: 退款政策（2026版）.pdf
```

正文规则：

- **PDF**：每页 `## 第 N 页`；`extract_tables()` 转 Markdown 表格；空页跳过
- **PPTX**：每页 `## 幻灯片 N`；文本框按形状顺序拼接；表格整表；图片原位插入 OCR 文字
- **DOCX**：Heading 1/2/3 → `#/##/###`；普通段落按原顺序；列表样式前缀 `- `；表格整表；图片原位
- **TXT**：`# <标题>` + 段落
- 表格：整表一个块，单元格内 `|` 转义、换行转 `<br>`；超长表格不按行拆分
- 图片文字以 `> 图片文字：…` 插入原位；OCR 失败或无文字则跳过（不产生占位噪声）
- 清理：去除控制字符（保留换行/制表），合并 3+ 连续空行为 2
- 总字符数超过 `MAX_DOC_CHARS` → 413

### doc_id 与标题

- 非 md：`doc_id = f"{format}-{sha256(原始字节)[:10]}"`，如 `pdf-3f9a2c71b8`
- 上传表单可选字段 `doc_id`（须满足现有 `^[a-z0-9][a-z0-9._-]{0,63}$`），填写则优先
- md 保持现有 frontmatter `doc_id` 规则（表单 `doc_id` 仅对非 md 生效）
- 标题：docx/pptx core properties `title` → PDF metadata `/Title`（非空且非 "Untitled"）→ 原文件名（保留中文）

## 存储布局

```
data/uploads/
├── <doc_id>.md                # 规范化产物（被扫描/索引）
├── .raw/<doc_id>.<ext>        # 原始文件
└── .assets/<doc_id>/image-01.png
```

- 现有 `_scan_dir` 只 glob 顶层 `*.md`，点目录天然不被扫描，**索引逻辑零改动**
- 删除文档时同步删除 `.raw/<doc_id>.*` 与 `.assets/<doc_id>/`
- 覆盖内置文档时，规范化产物写入 `uploads/<doc_id>.md`，沿用现有覆盖/回退语义

## 配置

| 变量 | 默认 | 说明 |
|---|---|---|
| `MAX_UPLOAD_BYTES` | `52428800`（50MB） | 由 2MB 提升，覆盖 PDF/PPT |
| `MAX_DOC_PAGES` | `100` | PDF 页数 / PPT 幻灯片数上限 |
| `MAX_DOC_CHARS` | `2000000` | 规范化后正文字符上限 |
| `IMAGE_OCR_ENABLED` | `true` | 关闭后跳过图片文字提取 |
| `OCR_MODEL` | `qwen-vl-ocr` | 兼容接口不可用时手动切 `qwen-vl-plus` |
| `MAX_ZIP_UNCOMPRESSED` | `209715200`（200MB） | DOCX/PPTX 解压总量上限 |
| `MAX_ZIP_ENTRIES` | `5000` | DOCX/PPTX zip 条目数上限 |

`.env.example` / README 同步更新。

## 接口与管理页

- `POST /api/kb/docs` 路径与响应结构保持兼容：`file`、`overwrite`，新增可选表单字段 `doc_id`
- 响应增加 `format` 字段：`{"doc_id","title","chunks","source":"uploads","format":"pdf"}`
- 管理页文件选择/拖拽接受 `.md,.txt,.pdf,.docx,.pptx`；增加可选的 doc_id 输入框
- 上传成功提示"已解析 N 个片段"；400/413 显示具体原因
- 其余接口（列表/读取/编辑/删除/检索）不变；页面编辑的是**规范化产物**，重新上传原文件会重新解析并覆盖手工修改

## 错误处理

| 场景 | 状态码 |
|---|---|
| 扩展名不支持、魔数与扩展名不符、解析失败、加密 PDF | 400 |
| 文件超限、页数超限、字符数超限、zip bomb（解压总量/条目数超限） | 413 |
| doc_id 已存在且未 overwrite | 409 |
| OCR 失败 / 无文字 | 不报错，记日志并跳过该图片 |

- DOCX/PPTX：先校验 zip 解压总大小与条目数（见配置），超限 → 413
- PDF 提取不到任何文字且无表格 → 400「未提取到文字，可能是扫描件（暂不支持）」
- OCR 失败不做自动降级：仅跳过该图片并记录日志；需要换模型时改 `OCR_MODEL`
- Pillow 无法识别的图片格式（如 EMF/WMF）跳过并记录日志
- 解析异常统一转 400，日志记录文件名与原因，不向客户端暴露堆栈

## 测试

- converter 单测（tmp_path 生成）：
  - TXT：UTF-8 与 GBK 编码
  - DOCX：标题层级、段落顺序、表格、内联图片（Pillow 生成 PNG）
  - PPTX：多页顺序、表格、图片
  - PDF：reportlab 生成两页英文 PDF（含表格），断言 `## 第 N 页`、表格 Markdown、顺序
- 组装/OCR：假 `ImageOcr` 返回文字，验证原位插入；抛错时跳过且不影响整体
- API：5 种格式上传 → 201 + 列表 + 可检索；魔数不符 400；超限 413；zip bomb 413；可选 doc_id 生效；冲突 409
- 回归：现有 88 个测试保持全绿；`ruff check` 干净

## 验收

1. 依次上传 txt/pdf/docx/pptx（含一张文字截图），管理页显示已入库，检索能命中页/幻灯片编号
2. 删除文档后 `.raw` 与 `.assets` 一并清理
3. 重启后文档仍在（规范化 md 被重新摄取），不重复向量化
4. 超限/伪装/损坏文件返回明确 4xx，服务不受影响
5. 关闭 `IMAGE_OCR_ENABLED` 后图片被跳过、其余内容正常入库

## 风险与后续

- 复杂中文版式 PDF 的阅读顺序可能不理想；后续可换 MinerU/Docling 或托管解析，converter 接口不变
- qwen-vl-ocr 走兼容接口若不可用，可用 `OCR_MODEL` 切换模型或改用 DashScope 原生 HTTP
- 后续 P2：扫描 PDF（RapidOCR/MinerU）、异步任务与进度、图表视觉描述、多模态 embedding
