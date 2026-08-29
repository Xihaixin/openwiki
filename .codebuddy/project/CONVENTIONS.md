# 编码约定

## 数据模型分层

| 位置 | 技术 | 用途 |
|---|---|---|
| `core/models/` | `dataclass` | 领域模型,承载业务数据 |
| `api/models.py` | Pydantic `BaseModel` | API 契约模型,承载 HTTP 请求/响应结构 |
| 各 router 模块内 | Pydantic `BaseModel` | 模块专属的请求模型(如 `system.py` 内的 `Model`/`Provider`/`ModelConfig`/`AuthorizationConfig`) |

依据:`api/models.py:7-10` 的分层说明。

## 配置加载

- 使用 **`dataclass` + `os.getenv` + `python-dotenv`**,**不用 pydantic-settings**。
- 在模块顶部执行 `load_dotenv()`。
- 配置按领域拆分为多个 dataclass:`PostgreSQLConfig`、`RedisConfig`、`EmbeddingConfig`、`LLMConfig`、`RetrievalConfig`、`ChunkConfig`、`CacheConfig`、`StorageConfig`。
- 聚合为 `Settings` dataclass,导出全局单例 `settings`(`infra/config/settings.py:180`)。
- 使用处直接 `from infra.config.settings import settings`。
- 动态值用 `@property` 暴露,如 `dsn`、`async_dsn`。

## 配置目录分工

`core/config/`、`api/config/`、`infra/config/` 三处并存,是历史演进结果。**权威来源是 `infra/config/settings.py`**;另外两处多为转发或兼容封装。新增配置项优先加在 `infra/config/settings.py`。

## 命名风格

- Python:模块/函数/变量 `snake_case`,类 `PascalCase`,常量 `UPPER_SNAKE_CASE`。
- 前端:变量与函数 `camelCase`,组件与类型 `PascalCase`。
- **API 契约字段用 camelCase**(`filePaths`、`relatedPages`、`repoUrl`、`submittedAt`),Python 内部字段用 snake_case(`repo_url`)。跨语言边界处需显式映射。

## 异步

- 数据库用 `asyncpg` / `AsyncDatabasePool`,异步风格贯穿基础设施层与 API 层。
- FastAPI 路由函数与 Flow 方法普遍为 `async def`。

## 错误处理

- 后端基础设施层与业务层:先确认项目内是否定义自定义异常,再决定抛异常还是返回降级值。
- API 层:FastAPI 的 `HTTPException` 或返回错误响应体。
- 前端 Route Handler(`src/app/api/*/route.ts`)统一模式:`try/catch` 包裹 `fetch`,后端非 2xx 时透传状态码,连接失败返回 503 并附 `error` 字段。见 `src/app/api/wiki_cache/route.ts:18-30`。

## 日志

- 日志配置集中在 `core/config/logging_config.py`。
- 全局日志级别与路径由 `settings.log_level`、`settings.log_file` 控制(默认写 `config/logs/infra.log`)。
- 前端侧在 Route Handler 中用 `console.error` 记录后端错误。

## 导入组织

- 标准库 → 第三方 → 本地,三段式分组。
- 跨层导入用绝对路径(如 `from infra.config.settings import settings`),项目内不使用相对导入跨层引用。

## 前端约定

- Next.js 15 App Router,页面在 `src/app/`,组件在 `src/components/`,Context 在 `src/contexts/`,自定义 Hook 在 `src/hooks/`,工具在 `src/utils/`,类型在 `src/types/`。
- 样式用 Tailwind(`tailwind.config.js`)。
- **访问后端优先走 Route Handler**(`src/app/api/*/route.ts`),而非直接在组件里 `fetch` 后端域名;这是当前推荐的代理模式。
- 后端地址通过环境变量 `PYTHON_BACKEND_HOST`(`next.config.ts` 用 `SERVER_BASE_URL`),默认 `http://localhost:8001`。
- 流式响应:SSE 用 `src/utils/sseClient.ts`,WebSocket 用 `src/utils/websocketClient.ts`。
- 国际化:`src/messages/*.json` + `src/i18n.ts` + `src/contexts/LanguageContext.tsx`。

## 数据库与迁移

- 迁移脚本集中在 `infra/migration/`:`runner.py` 为执行入口,`scripts/` 存放 `.sql` 与 Python 迁移脚本,`pkl_to_pg_v3.py` 负责 pickle → PostgreSQL 的历史数据迁移。
- SQL 为**手工维护**,改表结构时需同步更新 `scripts/` 下的 `.sql`。

## 缓存

- `infra/cache/` 封装 Redis 缓存,TTL 按用途区分(见 `RedisConfig`):embedding 24h、语义缓存 1h、仓库锁 5min、进度 10min。
- 后端可切换:`CACHE_BACKEND=filesystem | db_redis`。
