-- ============================================================================
-- openwiki — retrieval_logs 增加检索溯源字段（task / source_id）
--
-- 适用：所有库。存量库（已执行 001/002/003）与新库（按 002 建库）都需要执行。
-- 幂等：全部使用 IF NOT EXISTS，可重复执行。
--
-- 背景：
--   HybridRetriever.search(task=..., source_id=...) 在写检索日志时记录
--   「这次检索是给谁用的」：
--     task      —— 检索用途：wiki_page / chat / research / unknown
--     source_id —— 业务来源主键：wiki_pages.id（wiki_page）或 qa_logs.id（chat/research）
--   由此可按页面反查该页面生成时检索命中了哪些分块（retrieval_results）。
--
-- 说明：
--   wiki_flow 在生成页面之前先 ensure_page 预创建 wiki_pages 行拿到主键，
--   后续 upsert 命中同一行（project_id + page_slug），主键稳定不变。
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 1. task 检索用途
-- ---------------------------------------------------------------------------
ALTER TABLE retrieval_logs
    ADD COLUMN IF NOT EXISTS task VARCHAR(50) NOT NULL DEFAULT 'unknown';

COMMENT ON COLUMN retrieval_logs.task IS
    '检索用途：wiki_page / chat / research / unknown';

-- ---------------------------------------------------------------------------
-- 2. source_id 业务来源主键（可为空：检索发生时来源尚未生成）
-- ---------------------------------------------------------------------------
ALTER TABLE retrieval_logs
    ADD COLUMN IF NOT EXISTS source_id UUID;

COMMENT ON COLUMN retrieval_logs.source_id IS
    '业务来源主键（wiki_pages.id / qa_logs.id），可空，后续可用 bind_source 回填';

-- ---------------------------------------------------------------------------
-- 3. 按「来源」反查检索记录的索引
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_rlogs_task_source
    ON retrieval_logs (task, source_id);
