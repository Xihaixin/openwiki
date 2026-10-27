-- ============================================================================
-- openwiki 数据库 Schema v0.1.4
-- 目标数据库：openwiki（由 infra/migration/runner.py 创建并应用）
--
-- 设计目标：
-- 为了精简数据处理流程，专注于最小 MVP 产品
--   - 删除项目中未使用到的数据表
--   - 保留几个用于审计的表结构 - 已验证可以正常使用
--   - 当前暂时不考虑 git 项目仓库的增量更新功能，需要先验证核心功能
--   - 

-- 与 v0.1.3 的差异：
--   R1. 删除 repository_files 表，它与 raw_documents 表功能高度重复
--   R2. 删除 raw_documents 表中有 dir_path 字段; 对应 RawDocument 类模型，里面根本就没有这个属性
--   R3. 删除 code_symbol 表，暂时不需要对文件进行更精细的区分
--   R4. 为 project 表添加 is_deleted 与 created_at 字段；删除 last_commit 字段
--   R5. 移除 wiki_structure 表中的 repo 信息（旧列使用存量库请执行 003 脚本）
--   R6. wiki_structure 保持 (project_id, language, is_comprehensive) 组成唯一键，换模型即生成覆盖

--
-- 配套代码改动（切换默认存储时同步进行）：
--   - WikiStructureRepository.upsert：ON CONFLICT (project_id, language, is_comprehensive)
--   - WikiPageRepository.upsert：ON CONFLICT (project_id, page_slug)
--   - WikiStructureRepository.delete：物理 DELETE → UPDATE is_deleted=TRUE（服务层先清 Redis）
--   - WikiStructureRepository.read/list：查询条件追加 is_deleted=FALSE
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------------------
-- 0. 通用类型
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'ingestion_status') THEN
        -- 摄取任务状态机：pending → cloning/parsing/chunking/embedding/indexing → completed/failed
        -- （与 infra/pipeline/ingestion.py 写入值一致）
        CREATE TYPE ingestion_status AS ENUM (
            'pending', 'cloning', 'parsing', 'chunking',
            'embedding', 'indexing', 'completed', 'failed'
        );
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 1. embedding_models —— 嵌入模型注册表
--    用途：嵌入向量入库前，通过 name 查询模型记录获取 model_id
--         （infra/pipeline/ingestion.py 硬编码按 settings.embedding.default_model 查询）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS embedding_models (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(100) NOT NULL UNIQUE,             -- 模型标识，如 text-embedding-v4
    provider    VARCHAR(50) NOT NULL,                     -- 模型提供商：dashscope/openai 等
    dimensions  INT NOT NULL,                             -- 有效输出维度 = 系统维度（见 CHECK 约束说明）
    description TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- 维度一致性约束（★核心设计决策）：
    --   向量检索要求「查询向量维度 == 库内向量维度」：用户问题编码为查询向量，
    --   SQL 以 embedding <=> %s::vector 比对时维度不匹配会直接报错。
    --   系统维度 = settings.embedding.default_dimensions = 256，与物理向量表
    --   chunk_embeddings_dim256 / retrieval_logs.query_embedding 的 VECTOR(256) 对齐。
    --   因此无论注册哪个提供商/模型，其【有效输出维度】必须等于 256。
    --   256 维是性能与质量/准确率的平衡点（OpenAI 官方数据：3-small 截断到
    --   256 维仍保留约 96% 的 MTEB 表现，存储与计算开销显著低于 1536/3072 维）。
    --   注意：支持 dimensions 参数截断的模型（如 OpenAI 3-small/3-large），
    --   此处记录【实际写入数据库的维度】而非模型最大维度；新增模型时必须
    --   满足「可输出 256 维向量」（原生或经 API 截断），否则检索/摄取会失败。
    CONSTRAINT ck_embedding_dims CHECK (dimensions = 256)
);

-- 种子数据：与 infra/config/settings.py embedding.default_model='text-embedding-v4' 对应；
-- 3-small/3-large 经 OpenAI dimensions 参数截断输出 256 维（代码 EmbeddingService
-- 已显式传 dimensions=self.dimensions=256），记录维度即为有效写入维度
INSERT INTO embedding_models (name, provider, dimensions, description) VALUES
    ('text-embedding-v4',       'dashscope', 256, '阿里云百炼通用文本向量（默认，原生 256 维）'),
    ('text-embedding-3-small',  'openai',    256, 'OpenAI 文本向量 small（dimensions 截断至系统维度 256）'),
    ('text-embedding-3-large',  'openai',    256, 'OpenAI 文本向量 large（dimensions 截断至系统维度 256）')
ON CONFLICT (name) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. projects —— 项目（代码仓库）登记
--    用途：用户提交仓库/本地路径时登记，作为所有业务数据的根（project_id）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS projects (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name             VARCHAR(255) NOT NULL,                -- 展示名，通常 "owner/repo"
    repo_url         TEXT,                                 -- 远程仓库地址（本地项目可为空，UNIQUE 允许多 NULL）
    owner            VARCHAR(255),                         -- 仓库归属者（本地项目可空；代码层用 "unknown" 兜底）
    repo_type        VARCHAR(50) NOT NULL DEFAULT 'github',-- 仓库平台类型：github/gitee/local，后续可扩展，不加 CHECK
    local_path       TEXT,                                 -- 本地项目路径
    is_deleted       BOOLEAN NOT NULL DEFAULT FALSE,       -- 软删除（重新摄取时自动恢复）
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata         JSONB NOT NULL DEFAULT '{}'           -- 扩展信息（如源 pickle 导入参数）
);

CREATE INDEX IF NOT EXISTS idx_projects_owner ON projects (owner);


-- ---------------------------------------------------------------------------
-- 3. raw_documents —— 原始文档（仅文本文件，每文件一行）
--    用途：RAG 解析的输入；file_path 保留相对路径（含目录层级，可重建结构）
--    写入：DocumentRepository.upsert（content_sha256 用于幂等去重）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    file_path       TEXT NOT NULL,                         -- 仓库内相对路径（含目录层级）
    file_type       VARCHAR(20),                           -- 文件后缀（如 "py"、"md"），由 read_all_documents 提取
    content         TEXT NOT NULL,                         -- 文件内容
    token_count     INT,                                   -- 估算 token 数
    is_code         BOOLEAN NOT NULL DEFAULT TRUE,         -- 是否代码文件（应由扩展名白名单判定；当前代码默认 True，见注①）
    is_deleted      BOOLEAN NOT NULL DEFAULT FALSE,        -- 软删除
    content_sha256  VARCHAR(64),                           -- 内容指纹（幂等去重）
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_raw_docs UNIQUE (project_id, file_path)
);

-- 注①：core/utils/documents.py 的 read_all_documents 不返回 is_code；
--       core/ingestion/ingestor.py 写入时默认 True（所有文件按代码处理），
--       is_code 影响分块策略与符号提取，建议后续统一为扩展名白名单判定。

CREATE INDEX IF NOT EXISTS idx_raw_docs_project ON raw_documents (project_id);
CREATE INDEX IF NOT EXISTS idx_raw_docs_sha ON raw_documents (content_sha256);

-- ---------------------------------------------------------------------------
-- 4. document_chunks —— 文档分块（RAG 检索单元）
--    用途：TextSplitter 按 file_type 策略（代码走行级分块）切分后的块
--    写入：ChunkRepository.batch_insert（chunk_size/chunk_overlap/split_by 为切分参数）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS document_chunks (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id   UUID NOT NULL REFERENCES raw_documents(id) ON DELETE CASCADE,
    chunk_index   INT NOT NULL,                            -- 块在文档内的序号
    content       TEXT NOT NULL,                           -- 块内容
    chunk_size    INT,                                     -- 切分块大小（字符数）
    chunk_overlap INT,                                     -- 块间重叠长度
    split_by      VARCHAR(50),                             -- 切分策略标识（如 "code_line"）
    token_count   INT,                                     -- 块 token 数（检索预算过滤用）
    start_offset  INT,                                     -- 块在原文中的起始偏移（源码定位用）
    end_offset    INT,                                     -- 块在原文中的结束偏移
    metadata      JSONB NOT NULL DEFAULT '{}',             -- 扩展信息
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_chunks UNIQUE (document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc ON document_chunks (document_id);

-- ---------------------------------------------------------------------------
-- 5. chunk_embeddings_dim256 —— 分块向量嵌入（256 维，text-embedding-v4）
--    用途：向量检索 + 全文检索（hybrid）的底层表
--    冗余字段说明：content/file_path/chunk_index 冗余存储，检索命中后直接返回，
--                  避免 JOIN document_chunks（HybridRetriever.search 的返回契约）
--    多模型并存：UNIQUE(chunk_id, model_id) 允许同一分块存在多套向量（按 model_id 区分）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chunk_embeddings_dim256 (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chunk_id     UUID NOT NULL REFERENCES document_chunks(id) ON DELETE CASCADE,
    project_id   UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    model_id     UUID NOT NULL REFERENCES embedding_models(id),
    embedding    VECTOR(256) NOT NULL,                     -- 向量（维度与表名 dim256 一致）
    content      TEXT,                                     -- 冗余：块内容
    file_path    TEXT,                                     -- 冗余：所属文件路径
    chunk_index  INT,                                      -- 冗余：块序号
    fts_text     TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple', coalesce(content, ''))) STORED,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_chunk_emb UNIQUE (chunk_id, model_id)
);

-- HNSW 余弦相似索引（近似最近邻，检索主路径）
CREATE INDEX IF NOT EXISTS idx_emb_hnsw ON chunk_embeddings_dim256
    USING hnsw (embedding vector_cosine_ops);
-- GIN 全文检索索引（hybrid 的关键词分支）
CREATE INDEX IF NOT EXISTS idx_emb_fts ON chunk_embeddings_dim256 USING gin (fts_text);
-- 项目过滤索引（检索按 project 限定）
CREATE INDEX IF NOT EXISTS idx_emb_project ON chunk_embeddings_dim256 (project_id);

-- ---------------------------------------------------------------------------
-- 6. ingestion_jobs —— 文档摄取任务（摄取/解析过程的状态机）
--    用途：记录一次摄取任务的完整生命周期：
--          create(pending) → update_status(cloning→parsing→chunking→embedding→indexing,
--          带 current_stage + progress + processed_files/total_files) → finalize(completed/failed)
--    写入：IngestionJobRepository（core/ingestion/ingestor.py）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ingestion_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    trigger_type    VARCHAR(50) NOT NULL DEFAULT 'manual', -- 触发方式：manual/push/scheduled
    status          ingestion_status NOT NULL DEFAULT 'pending', -- 任务状态机
    current_stage   VARCHAR(50),                           -- 当前阶段描述（如 "embedding 12/45"）
    progress        FLOAT NOT NULL DEFAULT 0.0,            -- 进度 0.0~1.0（repository 传浮点，保持契约）
    total_files     INT NOT NULL DEFAULT 0,                -- 待处理文件总数
    processed_files INT NOT NULL DEFAULT 0,                -- 已处理文件数
    error_message   TEXT,                                  -- 失败时的错误信息
    error_detail    JSONB,                                 -- 失败详情（结构化）
    started_at      TIMESTAMPTZ,                           -- 任务开始时间
    completed_at    TIMESTAMPTZ,                           -- 任务完成/失败时间
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_jobs_project ON ingestion_jobs (project_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON ingestion_jobs (status);

-- ---------------------------------------------------------------------------
-- 7. pipeline_logs —— 管道运行日志（摄取各步骤明细）
--    用途：每个阶段（download/parse/chunk/embed/index）执行后记录一条，
--          用于排障与性能观测；由 PipelineLogRepository.log 写入
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pipeline_logs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id    UUID REFERENCES projects(id) ON DELETE CASCADE,
    job_id        UUID REFERENCES ingestion_jobs(id) ON DELETE SET NULL,
    step_name     VARCHAR(100),                            -- 步骤名：parse / chunk / embed / index...
    status        VARCHAR(20),                             -- success / failed / skipped
    input_count   INT,                                     -- 输入记录数（如解析的文档数）
    output_count  INT,                                     -- 输出记录数（如生成的块数）
    duration_ms   INT,                                     -- 步骤耗时（毫秒）
    error_message TEXT,                                    -- 失败信息
    parameters    JSONB,                                   -- 步骤参数快照（如分块参数）
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_plogs_project ON pipeline_logs (project_id);
CREATE INDEX IF NOT EXISTS idx_plogs_job ON pipeline_logs (job_id);

-- ---------------------------------------------------------------------------
-- 8. retrieval_logs —— 检索日志（一次检索的请求）
--    用途：HybridRetriever.search 每次执行记录一条（log_retrieval=True 时）：
--          query 原文 + 查询向量 + 检索参数 + 耗时
--    写入：RetrievalRepository.log_retrieval
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS retrieval_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID REFERENCES projects(id) ON DELETE CASCADE,
    query_text      TEXT NOT NULL,                         -- 用户查询原文
    query_embedding VECTOR(256),                           -- 查询向量（text-embedding-v4 编码）
    top_k           INT NOT NULL DEFAULT 5,                -- 请求返回条数
    retrieval_type  VARCHAR(50) NOT NULL DEFAULT 'vector_only', -- hybrid / vector_only / fulltext
    hybrid_weight   FLOAT NOT NULL DEFAULT 0.7,            -- 向量/关键词融合权重（0.7=向量优先）
    latency_ms      INT,                                   -- 检索耗时（毫秒）
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rlogs_project ON retrieval_logs (project_id);

-- ---------------------------------------------------------------------------
-- 9. retrieval_results —— 检索结果明细（命中块 + 评分）
--    用途：一次检索返回的每个命中块一行，记录向量分/关键词分/融合分
--    写入：RetrievalRepository.log_results
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS retrieval_results (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    retrieval_id  UUID NOT NULL REFERENCES retrieval_logs(id) ON DELETE CASCADE,
    chunk_id      UUID REFERENCES document_chunks(id),     -- 命中的分块（chunk 删除后保留记录）
    rank          INT,                                     -- 排名（1 = 最相关）
    vector_score  FLOAT,                                   -- 向量余弦相似度分
    keyword_score FLOAT,                                   -- 关键词 BM25 分
    final_score   FLOAT,                                   -- 融合后最终分（hybrid_weight 加权）
    metadata      JSONB NOT NULL DEFAULT '{}',             -- 扩展信息（如来源文件路径）
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_retrieval_results UNIQUE (retrieval_id, chunk_id)
);

CREATE INDEX IF NOT EXISTS idx_rresults_log ON retrieval_results (retrieval_id);

-- ---------------------------------------------------------------------------
-- 10. qa_logs —— 问答日志
--    用途：每次 LLM 问答记录一条（含检索关联、token 用量、耗时、用户反馈）
--    写入：RAGEngine.log_qa（chat_flow/research_flow/websocket 均调用）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS qa_logs (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    retrieval_id      UUID REFERENCES retrieval_logs(id), -- 关联的检索记录（无检索时为 NULL）
    project_id        UUID REFERENCES projects(id) ON DELETE CASCADE,
    query_text        TEXT NOT NULL,                       -- 用户问题原文
    response_text     TEXT,                                -- LLM 回答
    model_name        VARCHAR(100),                        -- 使用的模型（如 qwen-plus）
    prompt_tokens     INT,                                 -- 输入 token 数
    completion_tokens INT,                                 -- 输出 token 数
    total_tokens      INT,                                 -- 总 token 数
    latency_ms        INT,                                 -- 生成耗时（毫秒）
    user_rating       INT,                                 -- 用户反馈评分 1-5
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_qa_project ON qa_logs (project_id);

-- ---------------------------------------------------------------------------
-- 11. wiki_structure —— Wiki 结构（原 wiki_caches，重命名）
--    用途：保存 LLM 生成的 Wiki 整体结构（目录骨架 + 元数据），
--          是 wiki_pages 的父级（一个结构对应一套页面）。
--    写入：前端「保存 Wiki」POST /api/wiki_cache → WikiStructureRepository.upsert
--    重要：structure_json 存【完整 WikiStructure 结构数据】（pages 骨架 +
--          sections + rootSections + repo + provider + model），读取时原样返回，
--          前端（WikiCacheData 模型）零拼装、零字段缺失。
--    is_comprehensive 维度：concise(精简) / comprehensive(全面) 两套缓存独立，
--          由 UNIQUE(project_id, language, is_comprehensive) 保证互不覆盖。
--    provider / model / language 收敛到结构级一份，wiki_pages 不再冗余存储。
--    软删除：删除 Wiki 结构不物理删行，置 is_deleted=TRUE（可恢复/可审计），
--           GET/list 查询统一过滤 is_deleted=FALSE
--    ★配套代码：WikiStructureRepository.upsert 的 ON CONFLICT 目标为 3 列
--          （project_id, language, is_comprehensive）；
--               delete 改 UPDATE is_deleted=TRUE；read/list 过滤 is_deleted=FALSE
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS wiki_structure (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id       UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    language         VARCHAR(16) NOT NULL DEFAULT 'zh',      -- Wiki 语言
    is_comprehensive BOOLEAN NOT NULL DEFAULT TRUE,          -- FALSE=concise, TRUE=comprehensive
    structure_json   JSONB NOT NULL DEFAULT '{}',            -- 完整 WikiStructure 结构 payload
    provider         VARCHAR(50),                            -- LLM 提供商
    model            VARCHAR(100),                           -- LLM 模型
    is_deleted       BOOLEAN NOT NULL DEFAULT FALSE,         -- 软删除标记（TRUE=已删除，不物理删行）
    deleted_at       TIMESTAMPTZ,                            -- 软删除时间（审计用）
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_wiki_structure UNIQUE (project_id, language, is_comprehensive)
);

CREATE INDEX IF NOT EXISTS idx_wiki_structure_project ON wiki_structure (project_id);

-- ---------------------------------------------------------------------------
-- 12. wiki_pages —— Wiki 页面内容（RAG 侧规范表）
--    用途：wiki_flow 生成页面时逐页写入（WikiPageRepository.upsert），
--          content_md 为 Markdown 内容，供 RAG 上下文/检索引用
--    与 wiki_structure 的关联：wiki_structure_id 外键溯源「页面属于哪次生成」；
--          language / is_comprehensive 收敛到结构级，页面通过外键关联获取
--    字段去重：provider / model / language 已从本表移除（保留在 wiki_structure），
--          避免两表冗余不一致。
--    补充字段：filePaths / importance / relatedPages 对齐前端 WikiPage 契约；
--          parentId / isSection / children 为目录树定位字段
--    ★配套代码：WikiPageRepository.upsert 的 ON CONFLICT 目标为
--          (project_id, page_slug)（is_comprehensive 已上移到结构级）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS wiki_pages (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    wiki_structure_id UUID REFERENCES wiki_structure(id) ON DELETE CASCADE, -- 归属结构（溯源）
    project_id        UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    page_slug         TEXT NOT NULL,                        -- 页面唯一标识（= 前端 WikiPage.id）
    title             TEXT NOT NULL,                        -- 页面标题
    content_md        TEXT,                                 -- 页面 Markdown 内容
    file_paths        JSONB NOT NULL DEFAULT '[]',          -- 相关源码文件路径列表
    importance        VARCHAR(16) NOT NULL DEFAULT 'medium',-- 重要度：high/medium/low
    related_pages     JSONB NOT NULL DEFAULT '[]',          -- 相关页面 ID 列表
    parent_id         TEXT,                                 -- 树定位：父节点 id（所属 section）
    is_section        BOOLEAN NOT NULL DEFAULT FALSE,       -- 树定位：是否本身是 section 节点
    children          JSONB NOT NULL DEFAULT '[]',          -- 树定位：子节点 id 列表
    version           INT NOT NULL DEFAULT 1,               -- 页面内容版本
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_wiki_pages UNIQUE (project_id, page_slug)
);

CREATE INDEX IF NOT EXISTS idx_wiki_pages_project ON wiki_pages (project_id);
CREATE INDEX IF NOT EXISTS idx_wiki_pages_structure ON wiki_pages (wiki_structure_id);

-- ---------------------------------------------------------------------------
-- 13. conversations —— Wiki 内对话会话
--    用途：用户在 Wiki 页内的问答会话（当前代码暂用内存对话，表为持久化预留；
--          page_slug 记录会话发生在哪个 Wiki 页，未来可做「页面级对话历史」）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS conversations (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id    UUID REFERENCES projects(id) ON DELETE CASCADE,
    page_slug     TEXT,                                     -- 会话所在 Wiki 页（页面级对话上下文）
    language      VARCHAR(16) NOT NULL DEFAULT 'zh',
    provider      VARCHAR(50),
    model         VARCHAR(100),
    title         TEXT,                                     -- 会话标题（前端列表展示）
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversations_project ON conversations (project_id);
CREATE INDEX IF NOT EXISTS idx_conversations_page ON conversations (page_slug);

-- ---------------------------------------------------------------------------
-- 14. conversation_turns —— 对话轮次
--    用途：会话内逐轮消息；token_count/latency_ms 用于成本与效果评估
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS conversation_turns (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    turn_index      INT NOT NULL,                           -- 轮次序号（会话内递增）
    role            VARCHAR(20) NOT NULL,                   -- user / assistant / system
    content         TEXT NOT NULL,                          -- 消息内容
    token_count     INT NOT NULL DEFAULT 0,                 -- 消息 token 数
    latency_ms      INT NOT NULL DEFAULT 0,                 -- 生成耗时（assistant 轮）
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_turns UNIQUE (conversation_id, turn_index),
    CONSTRAINT ck_turn_role CHECK (role IN ('user', 'assistant', 'system'))
);

CREATE INDEX IF NOT EXISTS idx_turns_conversation ON conversation_turns (conversation_id);
