# 项目概况

## 项目定位

**OpenWiki-open**(包名 `openwiki`)。毕业设计项目:透明化 RAG 系统优化。

核心工作是将 deepwiki-open 的 RAG 后端从 **FAISS + pickle** 重构为 **PostgreSQL + pgvector + Redis**,使检索过程可观测、可管理。前端保留 Next.js App Router,通过 BFF 代理访问 Python 后端。

## 技术栈

| 层面 | 选型 |
|---|---|
| 后端 | Python + FastAPI,默认端口 **8001** |
| 前端 | Next.js 15 App Router + TypeScript + Tailwind,产物 `output: 'standalone'` |
| 存储 | PostgreSQL + pgvector(可回退 faiss,`STORAGE_BACKEND` 切换) |
| 缓存 | Redis(可回退 filesystem JSON,`CACHE_BACKEND` 切换) |
| 嵌入模型 | DashScope `text-embedding-v4`,维度 **256** |
| 大模型 | DashScope `qwen-plus` |

## 关键入口

| 用途 | 路径 |
|---|---|
| API 服务 | `api/main.py:114` — `app = FastAPI(...)`,lifespan 中初始化 `AsyncDatabasePool` 并挂到 `app.state.db_pool` |
| WebSocket | `api/main.py:134` — `/ws/chat` → `api/websocket_wiki.py:handle_websocket_chat` |
| CLI | `core/cli.py` — `python -m core.cli --mode <ingest\|wiki\|chat\|research>` |
| 数据库迁移 | `infra/migration/runner.py:164` — `main()` |
| RAG 引擎 | `core/rag_engine.py:58` — `class RAGEngine` |
| 前端首页 | `src/app/page.tsx` |
| 前端 BFF 代理 | `next.config.ts`(rewrites)+ `src/app/api/*/route.ts`(Route Handler) |

## 当前版本

`2.0.0`(`api/main.py` 与 `infra/__init__.py` 均声明)

## 路由清单

聚合点 `api/routers/__init__.py:28-36` 组装 `api_router`。

| 模块 | 端点 |
|---|---|
| `system.py` | `GET /lang/config`、`GET /auth/status`、`POST /auth/validate`、`GET /models/config` |
| `wiki_cache.py` | `GET/POST/DELETE /api/wiki_cache`、`GET /api/processed_projects` |
| `export.py` | `POST /export/wiki` |
| `local_repo.py` | `GET /local_repo/structure` |
| `wiki.py` | `POST /wiki/generate`、`POST /wiki/generate/page` |
| `chat.py` | `POST /chat/completions/stream` |
| `meta.py` | `GET /health` |

> 注意:`wiki.py` 导出的是 `wiki_router`,其余模块导出 `router`,聚合时需区分(见 `api/routers/__init__.py:25`)。
