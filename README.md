# OpenWiki-open

> 毕业设计项目：**透明化 RAG 系统的设计与优化**
> 包名 `openwiki`，当前版本 `2.0.0`

OpenWiki-open 是在 [deepwiki-open](https://github.com/AsyncFuncAI/deepwiki-open) 基础上重构的「代码仓库 → 智能 Wiki」系统。它保留原项目的产品形态（输入仓库地址，自动生成结构化 Wiki 文档并支持基于仓库的问答），但把底层 RAG 存储彻底换成了 **PostgreSQL + pgvector + Redis**，使检索过程可观测、可管理、可评估。

**与原项目的核心差异**

| 维度 | deepwiki-open（原版） | OpenWiki-open（本项目） |
|---|---|---|
| 向量存储 | FAISS + `.pkl` 本地文件 | PostgreSQL + pgvector（`VECTOR(256)`，HNSW 索引） |
| 元数据 | 全部塞在 pickle 里 | 17 张关系表（项目/文档/分块/嵌入/任务/日志/缓存） |
| 检索方式 | 纯向量 | 混合检索：向量 + 全文（tsvector/GIN）+ 加权/RRF 融合 |
| 过程可观测 | 无 | `ingestion_jobs` / `pipeline_logs` / `retrieval_logs` / `retrieval_results` / `qa_logs` 全链路落库 |
| 缓存 | 无 | Embedding 缓存、语义缓存、Wiki 双层缓存（PG 持久化 + Redis 加速） |
| 后端结构 | 单文件 `api/api.py` 大杂烩 | 四层单向依赖：`api` → `core` → `infra` / `clients` |

---

## 目录

- [技术栈](#技术栈)
- [目录结构](#目录结构)
- [快速开始](#快速开始)
- [环境变量](#环境变量)
- [数据库 Schema](#数据库-schema)
- [API 一览](#api-一览)
- [命令行工具](#命令行工具)
- [架构与分层约定](#架构与分层约定)
- [开发约定](#开发约定)
- [常见问题](#常见问题)
- [当前状态与待办](#当前状态与待办)

---

## 技术栈

### 后端（Python）

| 组件 | 选型 | 说明 |
|---|---|---|
| Web 框架 | FastAPI + Uvicorn | 默认监听 `0.0.0.0:8001` |
| 数据库 | PostgreSQL + pgvector | 异步 `asyncpg` 连接池 + 同步 `psycopg2`（脚本/迁移） |
| 缓存 | Redis | 可选，未启动时自动降级，不影响主流程 |
| ORM / 数据访问 | SQLAlchemy 模型定义（`infra/db/models.py`）+ 手写 SQL Repository | 迁移脚本为手工维护的 `.sql` |
| 嵌入模型 | DashScope `text-embedding-v4`，维度 **256** | 维度是跨层隐式契约，见 [常见问题](#常见问题) |
| 大模型 | DashScope `qwen-plus`（默认），另支持 Google / OpenAI / OpenRouter / Ollama | 统一由 `clients/llm.py` 调度 |
| 运行环境 | Python ≥ 3.12，依赖由 `uv` 管理（`uv.lock`） | 打包范围 `core*` / `infra*` / `api*` / `clients*` |

### 前端（TypeScript）

| 组件 | 选型 |
|---|---|
| 框架 | Next.js 15（App Router）+ React 19 |
| 语言 / 样式 | TypeScript + Tailwind CSS 4 |
| 输出 | `output: 'standalone'`（便于容器化） |
| 国际化 | `next-intl` + `src/messages/*.json`（10 种语言） |
| 其他 | `react-markdown`、`mermaid`（图表渲染）、`svg-pan-zoom`、`next-themes` |

---

## 目录结构

```
rag_build/
├── api/                      # 协议层：路由、DTO、SSE/WebSocket 封装，不含业务逻辑
│   ├── main.py               # ★ FastAPI 唯一入口（组合根：lifespan 管理 DB 连接池）
│   ├── models.py             # ★ 跨模块共享的 Pydantic 契约（与前端字段强绑定）
│   ├── websocket_wiki.py     # /ws/chat 处理
│   └── routers/              # system / wiki_cache / export / local_repo / wiki / chat / meta
│
├── core/                     # 业务层：流程编排、领域模型、Prompt、CLI
│   ├── flows/                # base / wiki_flow（Wiki 生成）/ chat_flow（问答）/ research_flow（深度研究）
│   ├── services/             # wiki_cache.py — 业务服务门面（api 只认它，不直连 infra）
│   ├── models/               # 领域模型（dataclass）
│   ├── ingestion/ingestor.py # DataIngestor：仓库 → DB 的摄取器
│   ├── rag_engine.py         # RAGEngine：检索 + 缓存 + 生成 + qa_logs 的公共入口
│   ├── prompts/              # Prompt 模板
│   ├── utils/                # documents / language / llm(协调层) / repo / sse
│   ├── config/               # LLM Provider 与鉴权配置
│   └── cli.py                # ★ 统一命令行入口
│
├── infra/                    # 基础设施层：不依赖 core / api
│   ├── config/               # settings.py（配置单源）+ paths.py
│   ├── db/                   # connection.py（连接池）+ repository.py + models.py
│   ├── cache/                # base(接口) / filesystem / wiki_cache(PG+Redis) /
│   │                         # embedding_cache / semantic_cache / repo_lock / redis_client
│   ├── retrieval/            # hybrid_retriever.py — 混合检索
│   ├── pipeline/             # ingestion.py — 分块 + 嵌入 + 落库流水线
│   ├── integration/          # deepwiki_adapter.py — 对原版接口的兼容适配
│   └── migration/            # pkl_to_pg_v3.py + scripts/*.sql
│
├── clients/                  # 外部客户端：llm.py（Provider 调度，只依赖 infra.config）
│
└── src/                      # 前端（Next.js App Router）
    ├── app/                  # 页面 + Route Handler（BFF 代理）
    ├── components/           # Ask / WikiTreeView / ProcessedProjects / ModelSelectionModal ...
    ├── contexts/ hooks/ utils/ types/ messages/
    └── i18n.ts
```

---

## 快速开始

### 1. 前置条件

- Python **≥ 3.12**（推荐配合 [uv](https://docs.astral.sh/uv/)）
- PostgreSQL **≥ 14**，且已安装 [pgvector](https://github.com/pgvector/pgvector) 扩展
- （可选）Redis ≥ 6 —— 不启动时所有 Redis 调用被 `try/except` 包裹并自动降级
- Node.js ≥ 18 + npm

### 2. 安装后端依赖

```bash
# 使用 uv（推荐，仓库已提供 uv.lock）
uv sync

# 或使用 pip
pip install -e .
```

### 3. 创建数据库并应用 Schema

```bash
# 1) 建库
createdb -U postgres openwiki

# 2) 应用 v2.0 Schema（幂等，可重复执行）
psql -U postgres -d openwiki -f infra/migration/scripts/openwiki/001_create_openwiki_schema.sql
```

脚本会自动安装 `vector` 与 `pgcrypto` 扩展，创建 **17 张表**及索引（含 HNSW 向量索引与 GIN 全文索引）。

> 历史遗留：`infra/migration/scripts/001_create_schema.sql` 是 v1.0 的旧 Schema（面向 `rag_optimizer` 库），**不要**在新环境使用；`infra/migration/pkl_to_pg_v3.py` 用于把原版 `.pkl` 数据迁移进 PostgreSQL（`python -m infra.migration.pkl_to_pg_v3`）。

### 4. 配置环境变量

在仓库根目录创建 `.env`（后端启动时由 `api/main.py` 自动加载）：

```bash
# ---- PostgreSQL ----
PGHOST=localhost
PGPORT=5432
PGDATABASE=openwiki
PGUSER=postgres
PGPASSWORD=<你的密码>

# ---- Redis（可选，未启动自动降级）----
REDIS_HOST=localhost
REDIS_PORT=6379

# ---- DashScope（嵌入 + LLM）----
DASHSCOPE_API_KEY=<你的密钥>

# ---- Wiki 缓存后端：db_redis（默认，PG+Redis 双层）| filesystem（本地 JSON，向后兼容）----
CACHE_BACKEND=db_redis

# ---- 可选：鉴权码 ----
OPENWIKI_AUTH_MODE=False
OPENWIKI_AUTH_CODE=

# ---- 可选：git clone 代理 ----
OPENWIKI_GIT_PROXY=false
```

> ⚠️ `.env` 含密钥，**不要提交到版本库**。

### 5. 启动后端

```bash
python -m api.main
# 或
uvicorn api.main:app --host 0.0.0.0 --port 8001 --reload
```

启动后访问：

- 根端点（列出全部路由）：<http://localhost:8001/>
- 交互式文档：<http://localhost:8001/docs>
- 健康检查：<http://localhost:8001/health>

端口与热重载由 `OpenWiki_HOST` / `OpenWiki_PORT` / `OpenWiki_RELOAD` 控制（注意大小写即代码中的写法）。

### 6. 启动前端

```bash
npm install
npm run dev      # http://localhost:3000
# 生产构建
npm run build && npm start
```

前端通过 `SERVER_BASE_URL` 指向后端（默认 `http://localhost:8001`）。

### 7. 一条命令走通全流程（CLI，无需前端）

```bash
# 摄取仓库（clone → 解析 → 分块 → 嵌入 → 落库）
python -m core.cli --mode ingest --repo-url https://github.com/owner/repo

# 生成 Wiki
python -m core.cli --mode wiki --repo-url https://github.com/owner/repo --language zh

# 问答
python -m core.cli --mode chat --repo-url https://github.com/owner/repo --query "这个项目怎么启动？"

# 深度研究（多轮迭代检索）
python -m core.cli --mode research --repo-url https://github.com/owner/repo --query "架构设计原理"
```

---

## 环境变量

**权威来源是 `infra/config/settings.py`**（`core/config/` 与 `api/config/` 多为转发/兼容封装，属历史演进结果）。配置以 `dataclass + os.getenv + python-dotenv` 加载，导出全局单例 `settings`。

| 变量 | 默认值 | 说明 |
|---|---|---|
| `PGHOST` / `PGPORT` / `PGDATABASE` / `PGUSER` / `PGPASSWORD` | `localhost` / `5432` / `infra` / `postgres` / `postgres` | PostgreSQL 连接 |
| `REDIS_HOST` / `REDIS_PORT` / `REDIS_PASSWORD` | `localhost` / `6379` / 空 | Redis 连接 |
| `DASHSCOPE_API_KEY` | 空 | 嵌入与 LLM 的 DashScope 密钥 |
| `CACHE_BACKEND` | `db_redis` | Wiki 缓存实现：`db_redis` \| `filesystem` |
| `STORAGE_BACKEND` | `pgvector` | 预留开关（`pgvector` \| `faiss`），当前代码路径均直接走 pgvector |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `OPENWIKI_AUTH_MODE` / `OPENWIKI_AUTH_CODE` | `False` / 空 | 前端访问鉴权码 |
| `OPENWIKI_CONFIG_DIR` | `api/config/` | Provider / 模型配置目录 |
| `OPENWIKI_GIT_PROXY` | 未设置 | 开启后 clone 时自动检测并使用代理 |
| `ADALFLOW_DIR` | 系统缓存目录 | 数据根目录（仓库克隆、缓存文件的落盘位置），由 `infra/config/paths.py` 解析 |

**Redis TTL（代码内固定，见 `RedisConfig`）**：Embedding 缓存 24h、语义缓存 1h、仓库处理锁 5min、进度信息 10min。

**检索 / 分块参数默认值**：`top_k=5`、检索方式 `hybrid`（向量权重 0.7 / 关键词 0.3）、语义缓存相似度阈值 0.95、分块大小 1000 / 重叠 200 / 按词切分。

---

## 数据库 Schema

新库 **`openwiki`**，Schema v2.0，17 张表，按业务流程分为六组：

| 分组 | 表 | 用途 |
|---|---|---|
| 模型注册 | `embedding_models` | 嵌入模型注册表，含 `CHECK (dimensions = 256)` 强制与 `VECTOR(256)` 对齐 |
| 项目与文件 | `projects`、`repository_files` | 仓库登记信息；完整文件树快照（含未被 RAG 收录的文件，`is_readme` 标识 README） |
| 文档与向量 | `raw_documents`、`document_versions`、`document_chunks`、`chunk_embeddings_dim256` | 原始文档正文、`content_sha256` 去重、版本快照、分块、256 维向量（HNSW + GIN 双索引） |
| 代码结构 | `code_symbols` | 符号表（qualified_name / 签名 / 行号 / 可见性） |
| 可观测性 | `ingestion_jobs`、`pipeline_logs`、`retrieval_logs`、`retrieval_results`、`qa_logs` | 摄取状态机、管道明细、检索请求与命中明细、问答日志 |
| 产物与会话 | `wiki_caches`、`wiki_pages`、`conversations`、`conversation_turns` | 生成的 Wiki 结构与页面正文；Wiki 内对话 |

关键约束：

- `wiki_caches` — `UNIQUE (project_id, language, comprehensive)`，支持 **concise / comprehensive** 两套产物独立共存；`structure_json` 存完整 payload（含 `generated_pages`），读取时零拼装
- `wiki_pages` — `UNIQUE (project_id, page_slug, language, is_comprehensive)`，外键 `wiki_cache_id` 溯源
- **软删除**：`wiki_caches` 通过 `is_deleted` / `deleted_at` 标记，删除后重跑同一项目会自动恢复（唯一约束命中软删除行）

数据访问统一走 `infra/db/repository.py` 的 Repository 类：`ProjectRepository`、`DocumentRepository`、`ChunkRepository`、`EmbeddingRepository`、`IngestionJobRepository`、`RetrievalRepository`、`PipelineLogRepository`、`WikiPageRepository`、`WikiCacheRepository`。

---

## API 一览

服务启动后，`GET /` 会自动遍历路由表返回全部端点。

### HTTP

| 方法 | 路径 | 说明 | 模块 |
|---|---|---|---|
| `GET` | `/lang/config` | 支持的语言列表 | `system.py` |
| `GET` | `/auth/status` | 是否启用鉴权码 | `system.py` |
| `POST` | `/auth/validate` | 校验鉴权码 | `system.py` |
| `GET` | `/models/config` | 可用的 Provider / 模型清单 | `system.py` |
| `GET` | `/api/wiki_cache` | 读取已生成的 Wiki（结构 + 页面） | `wiki_cache.py` |
| `POST` | `/api/wiki_cache` | 保存生成的 Wiki | `wiki_cache.py` |
| `DELETE` | `/api/wiki_cache` | 删除指定 Wiki（软删除） | `wiki_cache.py` |
| `GET` | `/api/processed_projects` | 已处理项目列表（仅由 `wiki_cache_service` 从存储层扫描：DB 实现查 `wiki_caches` 表，文件系统实现扫缓存目录） | `wiki_cache.py` |
| `POST` | `/wiki/generate` | 生成完整 Wiki（**SSE 流式**） | `wiki.py` |
| `POST` | `/wiki/generate/page` | 生成单个页面（**SSE 流式**） | `wiki.py` |
| `POST` | `/chat/completions/stream` | 问答 / 深度研究（**SSE 流式**） | `chat.py` |
| `POST` | `/export/wiki` | 导出 Markdown / JSON | `export.py` |
| `GET` | `/local_repo/structure` | 读取本地仓库目录结构 | `local_repo.py` |
| `GET` | `/health` | 健康检查 | `meta.py` |

### WebSocket

`WS /ws/chat` —— 接收 JSON 请求，逐 token 推送纯文本分片，以 `[DONE]` 结束，出错发送 `[ERROR: ...]`。兼容原版 deepwiki-open 前端协议。

### SSE 事件类型

Wiki 生成流（`POST /wiki/generate`）：

| 事件 | 含义 |
|---|---|
| `progress` | 阶段进度（`fetch_structure` / `determine_structure` / `fetch_structure_done` 等） |
| `structure` | Wiki 结构确定完成 |
| `page_progress` | 单页生成进度 |
| `page_complete` | 单页生成完成 |
| `complete` | 全部完成 |
| `error` | 出错 |

### 前端代理（BFF）

前端到后端有**两条**并存通道，改动端点时两边都要查：

1. `next.config.ts` 的 5 条静态 `rewrites`（`/export/wiki`、`/local_repo/structure`、`/api/auth/*`、`/api/lang/config`）
2. `src/app/api/` 下的 7 个 Route Handler（推荐模式）：`wiki_cache`、`wiki/projects`、`wiki/generate`、`chat/stream`、`auth/status`、`auth/validate`、`models/config`

Route Handler 统一用 `try/catch` 包裹 `fetch`，后端非 2xx 原样透传状态码，连接失败返回 `503` 并附 `error` 字段。

---

## 命令行工具

`python -m core.cli --mode <ingest|wiki|chat|research> [options]`

| 参数 | 说明 | 默认 |
|---|---|---|
| `--mode, -m` | `ingest` / `wiki` / `chat` / `research` | `wiki` |
| `--repo-url, -u` | 仓库 URL；未指定且给了 `--local-path` 时自动推导为 `file:///` 形式 | — |
| `--local-path` | 本地仓库路径（ingest / wiki 模式通用） | — |
| `--repo-type` | `github` / `gitlab` / `bitbucket` / `gitee`（仅 ingest） | `github` |
| `--token` | Git 访问令牌（仅 ingest） | — |
| `--query, -q` | 问题（chat / research） | 「这个项目的主要功能是什么？」 |
| `--provider, -p` | LLM Provider | `dashscope` |
| `--model` | 模型名 | `qwen-plus` |
| `--language, -l` | 语言代码 | `zh` |
| `--concise, -c` | Wiki 简洁模式（否则 comprehensive） | 关闭 |
| `--no-db` | 不连数据库，用 fixtures 样本数据 | 关闭 |

Wiki 模式下若数据库无该项目数据，`WikiGenerationFlow` 会**自动触发摄取流水线**，无需手动先跑 `ingest`。

---

## 架构与分层约定

### 依赖方向（严格单向，禁止反向）

```
src/  (Next.js)
   ├─ rewrites (next.config.ts)  ─┐
   └─ Route Handler (src/app/api) ┴─HTTP─▶  api/
                                              └─▶ core/  ──▶ infra/  ──▶ PostgreSQL / Redis
                                                    └──────▶ clients/ ──▶ infra.config
```

- `api` 依赖 `core`（业务服务门面），**不直接依赖 `infra`** —— 唯一例外是组合根 `api/main.py`，它负责装配 DB 连接池
- `core` 依赖 `infra` 的抽象接口与 `clients`；配置解析与客户端调用由 `core/utils/llm.py` 协调层组装
- `infra` **不依赖** `core` / `api` / `clients`（路径类配置已下沉到 `infra/config/paths.py` 与 `infra/cache/paths.py` 以消除反向依赖）
- `clients` 只依赖 `infra.config`

各层 `__init__.py` 中写有依赖方向声明，属团队显式约定。

### 修改联动清单

改动前务必逐条核对：

| 改动对象 | 必须同步检查 |
|---|---|
| `core/services`、`core/flows` 的返回结构 | `api/models.py` 的 Pydantic DTO |
| `api/models.py` 的字段名 | 前端契约：`src/types/`、各 Route Handler、`ProcessedProjects.tsx` 等调用处 |
| 后端端点路径 / HTTP 方法 | **两处都查**：`next.config.ts` 的 `rewrites` 与 `src/app/api/*/route.ts` |
| `infra/db` 表结构 | `infra/migration/scripts/**/*.sql` **和** `infra/retrieval/`、`infra/db/repository.py` 中的 SQL |
| 嵌入维度（当前 **256**） | 建表语句的 `vector(N)`、`embedding_models` 的 CHECK 约束，以及**已存数据**（维度不匹配需重建索引与数据） |
| `infra/config/settings.py` 新增配置项 | `.env` 文件，以及 `core/config/`、`api/config/` 的转发封装 |
| `infra/cache` 抽象接口 | `core/flows/base.py:_init_retriever()` 等调用点 |
| `core/prompts/` 提示词 | `core/flows/` 中引用该提示词的位置 |

---

## 开发约定

- **数据模型分层**：`core/models/` 用 `dataclass`（领域模型）；`api/models.py` 与各 router 模块内用 Pydantic `BaseModel`（API 契约）
- **命名**：Python `snake_case` / `PascalCase`；前端 `camelCase` / `PascalCase`。**API 契约字段用 camelCase**（`filePaths`、`repoUrl`、`submittedAt`），Python 内部用 snake_case（`repo_url`），跨语言边界显式映射
- **异步**：数据库异步用 `asyncpg`，同步脚本用 `psycopg2`（`infra/db/connection.py` 同时提供 `AsyncDatabasePool` 与 `sync_conn`）；FastAPI 路由与 Flow 方法普遍为 `async def`
- **日志**：统一由 `core/config/logging_config.py` 配置，级别与路径取自 `LOG_LEVEL` / `LOG_FILE_PATH`，默认写 `config/logs/`
- **配置加载**：不使用 `pydantic-settings`，统一 `dataclass + os.getenv + python-dotenv`，模块顶部 `load_dotenv()`
- **前端访问后端**：优先走 Route Handler，而非在组件里直接 `fetch` 后端域名；流式响应用 `src/utils/sseClient.ts`（SSE）与 `src/utils/websocketClient.ts`（WebSocket）
- **数据库迁移**：`.sql` 手工维护，改表结构时同步更新 `infra/migration/scripts/`

---

## 常见问题

**1. 项目列表返回空 / 字段缺失**
`ProcessedProjectEntry.comprehensive` 是必填字段，历史上曾漏传导致 `ValidationError` 被静默吞掉。已修复（`api/routers/wiki_cache.py`），改动该 DTO 时注意同步前端 `ApiProcessedProject` 类型。

**2. 嵌入维度不匹配**
`settings.embedding.default_dimensions`（256）必须与 `chunk_embeddings_dim256` 的 `VECTOR(256)` 一致。更换嵌入模型时，需同时改维度配置、**重建表与索引并重跑摄取**，已有向量不可复用。

**3. Redis 没启动会怎样？**
不会崩。所有 Redis 调用均被 `try/except` 包裹并自动降级，PostgreSQL 作为主存储保证数据完整，仅失去加速效果。

**4. 缓存后端怎么切换？**
`.env` 设置 `CACHE_BACKEND=filesystem` 切回本地 JSON 文件缓存（向后兼容）；`db_redis`（默认）走 PG 持久化 + Redis 加速。`core/services/wiki_cache.py` 会按配置装配对应实现，调用方零感知。

**5. 仓库名含下划线时缓存对不上？**
`infra/cache/key.py` 已去除 `_` → `-` 的字符替换，与前端 `page.tsx` 的 `getCacheKey()` 完全一致。不要重新引入任何字符改写。

**6. 两个仓库被误判为同一个？**
`core/utils/repo.py` 提供 `normalize_repo_url` / `repo_urls_match`（去认证信息、去尾斜杠与 `.git`、host 小写后精确比较），`core/flows/base.py:_find_project_id` 使用它，避免 `owner/repo` 与 `owner/repo2` 的宽松子串匹配。

**7. 聊天是"假流式"吗？**
不是。`SimpleChatFlow.stream()` 是真流式（`call_llm_stream_raw` 逐块 yield），WebSocket 与深度研究分支行为一致，早期的 50 字符伪切片已移除。

---

## 当前状态与待办

**已完成**（详见 `.aidocs/` 中的设计与执行记录）

- [x] 后端四层分层与单向依赖收敛（原 `rag_optimizer/` → `infra/`）
- [x] 消除 FastAPI 双 app 实例，统一为 `api/main.py` 单入口 + `api/routers/`
- [x] Wiki 缓存接口化（`WikiCacheStorage`）+ 双实现 + `CACHE_BACKEND` 开关
- [x] 配置单源收敛到 `infra/config/settings.py`
- [x] 死代码清理（`llm_clients/`、`adalflow_processing.py`、`api/data_pipeline.py` 等）
- [x] P0/P1 缺陷修复：`comprehensive` 漏传、语言硬编码、`O(n²)` 去重、doc_map 与 retriever 复用、URL 粗糙匹配
- [x] 流式协议统一（真流式）
- [x] `openwiki` 库 Schema v2.0 落地 + Wiki 缓存软删除 + 前端契约同步
- [x] 默认缓存后端切换到 `db_redis`

**待办**

- [ ] 旧库 `rag_optimizer` 的历史数据（`raw_documents` 正文、`chunk_embeddings_dim256` 向量）迁移至 `openwiki`，范围待确认
- [ ] `infra/db/repository.py` 中 `sync_conn.execute` 返回 `Optional[list]`，`result[0]` 模式存在 Pylance 告警，可统一窄化类型
- [ ] 引入 pytest 补充接口 / 缓存 / 配置层的回归测试（当前未引入任何测试框架）
- [ ] 前后端契约自动生成（当前 `src/types/` 为手工维护，可考虑接入 OpenAPI 生成）
- [ ] 统一前端代理路径（rewrites 与 Route Handler 二选一）
- [ ] `infra/db/dump_pkl_data_03.py`、`infra/migration/scripts/populate_wiki_caches.py` 等一次性脚本的去留梳理
