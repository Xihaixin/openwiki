# 架构与修改联动清单

## 分层结构

| 层 | 目录 | 职责 |
|---|---|---|
| 表现层 | `src/` | Next.js 页面、组件、Context、BFF 代理 |
| 协议层 | `api/` | 请求解析、SSE 封装、鉴权码校验、DTO 校验。**不含业务逻辑** |
| 业务层 | `core/` | 业务流编排(`flows/`)、领域模型(`models/`)、服务门面(`services/`)、摄取(`ingestion/`)、Prompt、RAG 引擎、CLI |
| 基础设施层 | `infra/` | DB 连接与 Repository、混合检索、摄取流水线、Redis 缓存、数据迁移 |
| 外部客户端 | `clients/` | LLM 调度(`dispatch_stream`)。只管"怎么调用",不含配置解析 |

## 依赖方向(严格单向)

```
src/ (Next.js)
   ├─ rewrites        next.config.ts(5 条静态规则)
   └─ Route Handler   src/app/api/*/route.ts(7 个)
        └─HTTP─▶ api/  ──▶ core/flows, core/models, core/services, core/utils, core/config
                              └─▶ clients/llm
                              └─▶ infra/*
clients/ ──▶ infra/config/settings
core/    ──▶ infra/ + clients/
infra/   ──▶ 仅 infra 内部
```

**禁止反向依赖:infra 层不得 import core 或 api。** 该约束被严格遵守——实测在 `infra/` 下搜索 `from core.` / `from api.` 为 0 匹配,且 `infra/cache/paths.py:7`、`infra/config/paths.py:9` 的注释明确记录了"从 core.config 下沉至此,消除 infra → core 的反向依赖"。

各 `__init__.py` 中写有依赖方向声明,属团队显式约定:`clients/__init__.py:10-12`、`core/services/__init__.py:7-8`、`core/flows/base.py:14-20`。

## 修改联动清单

**这是精准修改最容易遗漏的地方,改动前务必逐条核对。**

| 改动对象 | 必须同步检查 |
|---|---|
| `core/services` / `core/flows` 的返回结构 | `api/models.py` 的 Pydantic DTO |
| `api/models.py` 的字段名 | 前端契约 —— `src/types/`(`wiki/`、`repoinfo.tsx`)及调用处。`api/models.py:12` 注释明确警告"字段名与前端契约严格绑定,改动需同步前端" |
| 后端端点路径或 HTTP 方法 | **两处都要查**:`next.config.ts` 的 `rewrites` **和** `src/app/api/*/route.ts` |
| `infra/db` 表结构 | `infra/migration/scripts/*.sql` **和** `infra/retrieval/` 中的检索 SQL |
| 嵌入维度(`settings.embedding.default_dimensions`,当前 256) | `infra/migration` 建表语句的 `vector(N)` 维度,以及**已存数据**(维度不匹配需重建索引与数据) |
| `infra/config/settings.py` 新增配置项 | 对应 `.env` 文件,以及 `core/config/`、`api/config/` 中的转发封装 |
| `infra/cache` 抽象接口 | `core/flows/base.py:_init_retriever()` 等调用点 |
| `core/prompts/` 提示词 | `core/flows/` 中引用该提示词的位置 |

## 已知易错点

1. **双重代理机制**。前端到后端存在两条通道:`next.config.ts` 的 5 条 `rewrites` 静态规则,与 `src/app/api/` 下 7 个 Route Handler。后者是新模式(`wiki_cache/route.ts:3-5` 注释写明"替代 next.config.ts 中的 rewrites 代理")。改动端点时只查一处必漏。
2. **路由导出名不一致**。`wiki.py` 导出 `wiki_router`,其余导出 `router`。
3. **DTO 分散定义**。`api/models.py` 只放跨模块共享的契约;各 router 的专属请求模型保留在 router 模块内部(如 `system.py` 的 `Model`/`Provider`/`ModelConfig`/`AuthorizationConfig`)。改 DTO 时先确认它到底在哪个文件。
4. **向量维度耦合**。嵌入模型配置维度与数据库表 `vector(N)` 维度必须一致,属于跨层隐式契约。
5. **配置目录三处并存**。`core/config/`、`api/config/`、`infra/config/` 是历史演进结果,存在重复或转发关系,修改配置时需确认权威来源在 `infra/config/settings.py`。
6. **字段名跨语言风格**。Python 侧用 snake_case(如 `repo_url`),前端契约字段用 camelCase(如 `filePaths`、`repoUrl`),映射处易出错。
