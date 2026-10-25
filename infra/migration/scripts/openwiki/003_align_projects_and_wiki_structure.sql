-- ============================================================================
-- openwiki v0.1.5 — 存量库对齐脚本
--
-- 适用：已经执行过 002（v0.1.4）的既有数据库；新库直接跑 002 即可，无需本脚本。
-- 幂等：全部使用 IF EXISTS / IF NOT EXISTS，可重复执行。
--
-- 内容：
--   1. wiki_structure 删除 repo_owner / repo_name / repo_type / repo_url
--      （与 projects 重复；列表页与读缓存改由 JOIN projects 提供）
--   2. projects 补充 is_deleted（软删除标记）
--   3. projects 补充 created_at（列表页 submittedAt 的数据源）
--   4. projects 删除 last_commit（代码中已无读取方）
--   5. 删除 v0.1.4 起不再创建的遗留表
--      （document_versions / repository_files / code_symbols）
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 1. wiki_structure 去仓库冗余列
-- ---------------------------------------------------------------------------
ALTER TABLE wiki_structure DROP COLUMN IF EXISTS repo_owner;
ALTER TABLE wiki_structure DROP COLUMN IF EXISTS repo_name;
ALTER TABLE wiki_structure DROP COLUMN IF EXISTS repo_type;
ALTER TABLE wiki_structure DROP COLUMN IF EXISTS repo_url;

COMMENT ON TABLE wiki_structure IS
    'Wiki 生成变体（project_id + language + is_comprehensive）；仓库信息见 projects';

-- ---------------------------------------------------------------------------
-- 2. projects 软删除标记
-- ---------------------------------------------------------------------------
ALTER TABLE projects ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE;

-- ---------------------------------------------------------------------------
-- 3. projects 创建时间（用于列表页 submittedAt）
--    存量行用 updated_at 回填，避免全部变成迁移时刻
-- ---------------------------------------------------------------------------
ALTER TABLE projects ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ;
UPDATE projects SET created_at = updated_at WHERE created_at IS NULL;
ALTER TABLE projects ALTER COLUMN created_at SET DEFAULT NOW();
ALTER TABLE projects ALTER COLUMN created_at SET NOT NULL;

-- ---------------------------------------------------------------------------
-- 4. projects 删除 last_commit（增量摄取水位线，当前无代码读取）
-- ---------------------------------------------------------------------------
ALTER TABLE projects DROP COLUMN IF EXISTS last_commit;

-- ---------------------------------------------------------------------------
-- 5. 清理遗留表（v0.1.4 起不再创建，代码中已无任何读写引用）
--
--    适用范围：仅存量库（由 001 建出的库）仍保留这三张表；
--    新库直接跑 002 不会创建它们，本段执行时全部为 no-op。
--
--    执行前建议确认无外部依赖（视图 / 其他 schema 的同名引用），
--    并确认已有数据库备份。CASCADE 会连带删除依赖对象。
-- ---------------------------------------------------------------------------

-- 文档历史快照：raw_documents 只保留最新版本，变更审计能力已由
-- content_sha256 去重 + document_chunks 重建代替
DROP TABLE IF EXISTS document_versions ;

-- 仓库文件树快照：与 raw_documents.file_path 功能重复，v0.1.4 已移除
DROP TABLE IF EXISTS repository_files CASCADE;

-- 代码符号表：当前生成链路不做符号级提取，v0.1.4 已移除
DROP TABLE IF EXISTS code_symbols CASCADE;
