"""
冒烟验证脚本：校验 wiki_structure / wiki_pages 表结构与代码对齐，并验证 Repository 可执行。

不做任何业务代码改动。两部分：
1. 结构探测 —— 用 AsyncDatabasePool(asyncpg) 查 information_schema，核对表/列/约束；
2. Repository 冒烟 —— 用 sync_conn(psycopg2，Repository 实际执行路径) 真实 upsert/get，
   验证 SQL 能跑通，结束后清理测试数据。

用法：
    .venv/Scripts/python.exe infra/migration/scripts/smoke_test_wiki_schema.py
"""

import asyncio
import sys
import uuid
from pathlib import Path
from typing import Any

# 将项目根目录加入 sys.path，保证 core 包可导入
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.config.settings import settings
from core.models.connection import AsyncDatabasePool, sync_conn

# ---------------------------------------------------------------------------
# 期望的表结构（与 001_create_openwiki_schema.sql + repository.py 严格一致）
# ---------------------------------------------------------------------------

EXPECTED_TABLES: dict[str, dict[str, Any]] = {
    "wiki_structure": {
        "columns": {
            "id", "project_id", "language", "is_comprehensive", "structure_json",
            "repo_owner", "repo_name", "repo_type", "repo_url",
            "provider", "model", "is_deleted", "deleted_at", "created_at", "updated_at",
        },
        "unique_constraints": {
            "uq_wiki_structure",
        },
    },
    "wiki_pages": {
        "columns": {
            "id", "wiki_structure_id", "project_id", "page_slug", "title", "content_md",
            "file_paths", "importance", "related_pages",
            "parent_id", "is_section", "children",
            "source_chunks", "version", "created_at", "updated_at",
        },
        "unique_constraints": {
            "uq_wiki_pages",
        },
    },
}

# 不得再存在于 wiki_pages 的冗余字段（已收敛到结构级）
DEPRECATED_PAGE_COLUMNS = {"language", "is_comprehensive", "provider", "model"}

PASS = "  [PASS]"
FAIL = "  [FAIL]"


# ---------------------------------------------------------------------------
# 1. 结构探测（asyncpg）
# ---------------------------------------------------------------------------

async def probe_schema() -> bool:
    """用 AsyncDatabasePool 探测表结构，与期望值逐项比对。"""
    pool = AsyncDatabasePool()
    await pool.init_pool()
    all_ok = True

    print(f"\n[1] 数据库: {settings.postgresql.database} (host={settings.postgresql.host}:{settings.postgresql.port})")

    for table, expect in EXPECTED_TABLES.items():
        print(f"\n--- 表 {table} ---")

        # 表是否存在
        async with pool.get_connection() as conn:
            rows = await conn.fetch(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = $1",
                table,
            )
        if not rows:
            print(f"{FAIL} 表 {table} 不存在")
            all_ok = False
            continue
        print(f"{PASS} 表存在")

        # 列
        async with pool.get_connection() as conn:
            cols = await conn.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = $1",
                table,
            )
        actual_cols = {r["column_name"] for r in cols}
        missing = expect["columns"] - actual_cols
        if missing:
            print(f"{FAIL} 缺少列: {sorted(missing)}")
            all_ok = False
        else:
            print(f"{PASS} 列齐全 ({len(expect['columns'])} 列)")

        if table == "wiki_pages":
            deprecated = DEPRECATED_PAGE_COLUMNS & actual_cols
            if deprecated:
                print(f"{FAIL} wiki_pages 仍存在应删除的冗余列: {sorted(deprecated)}")
                all_ok = False
            else:
                print(f"{PASS} 冗余列已移除 (language/is_comprehensive/provider/model)")

        # 唯一约束
        async with pool.get_connection() as conn:
            uniq = await conn.fetch(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = $1::regclass AND contype = 'u'",
                table,
            )
        actual_uniq = {r["conname"] for r in uniq}
        missing_uniq = expect["unique_constraints"] - actual_uniq
        if missing_uniq:
            print(f"{FAIL} 缺少唯一约束: {sorted(missing_uniq)}")
            all_ok = False
        else:
            print(f"{PASS} 唯一约束齐全: {sorted(actual_uniq)}")

    # 外键：wiki_pages.wiki_structure_id -> wiki_structure.id
    async with pool.get_connection() as conn:
        fk = await conn.fetch(
            "SELECT 1 FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON tc.constraint_name = kcu.constraint_name "
            "WHERE tc.constraint_type = 'FOREIGN KEY' "
            "  AND tc.table_name = 'wiki_pages' "
            "  AND kcu.column_name = 'wiki_structure_id'"
        )
    if fk:
        print(f"\n{PASS} 外键 wiki_pages.wiki_structure_id -> wiki_structure 存在")
    else:
        print(f"\n{FAIL} 缺少外键 wiki_pages.wiki_structure_id")
        all_ok = False

    await pool.close_pool()
    return all_ok


# ---------------------------------------------------------------------------
# 2. Repository 冒烟（psycopg2 sync_conn）
# ---------------------------------------------------------------------------

def smoke_repository() -> bool:
    """用 Repository 真实执行路径（sync_conn）做 upsert/get 冒烟。"""
    from core.models.repository import WikiStructureRepository, WikiPageRepository

    all_ok = True
    lang = "zh"

    # 先创建临时 projects 记录（wiki_structure/wiki_pages 的 project_id 外键依赖它）
    result = sync_conn.execute(
        "INSERT INTO projects (name, owner, repo_type) "
        "VALUES (%s, %s, %s) RETURNING id",
        ("smoke-test-repo", "smoke-owner", "github"),
    )
    test_project_id = str(result[0]["id"])

    print(f"\n[2] Repository 冒烟 (临时 project_id={test_project_id})")

    try:
        # --- 2.1 WikiStructureRepository.upsert ---
        structure_json = {
            "id": test_project_id, "title": "smoke", "description": "test",
            "pages": [], "sections": [], "rootSections": [],
        }
        structure_id = WikiStructureRepository.upsert(
            project_id=test_project_id,
            language=lang,
            structure_json=structure_json,
            is_comprehensive=True,
            repo_owner="smoke-owner", repo_name="smoke-repo",
            repo_type="github", provider="openai", model="gpt-4",
        )
        print(f"{PASS} WikiStructureRepository.upsert -> id={structure_id}")

        # --- 2.2 get_by_project ---
        rec = WikiStructureRepository.get_by_project(test_project_id, lang, True)
        if rec and rec.get("is_comprehensive") is True and rec.get("repo_name") == "smoke-repo":
            print(f"{PASS} WikiStructureRepository.get_by_project 命中 (is_comprehensive=True)")
        else:
            print(f"{FAIL} get_by_project 结果异常: {rec}")
            all_ok = False

        # --- 2.3 WikiPageRepository.upsert ---
        page_id = WikiPageRepository.upsert(
            project_id=test_project_id,
            page_slug="intro",
            title="Intro",
            content_md="# Intro",
            wiki_structure_id=structure_id,
            file_paths=["a.py"],
            importance="high",
            related_pages=["install"],
            parent_id="sec-1",
            is_section=False,
            children=["child-1"],
            source_chunks=[{"chunk_id": "c1"}],
        )
        print(f"{PASS} WikiPageRepository.upsert -> id={page_id}")

        # --- 2.4 get_by_project / get_by_slug ---
        pages = WikiPageRepository.get_by_project(test_project_id)
        if pages and len(pages) == 1:
            p = pages[0]
            checks = {
                "page_slug": p.get("page_slug") == "intro",
                "importance": p.get("importance") == "high",
                "file_paths": p.get("file_paths") == ["a.py"],
                "related_pages": p.get("related_pages") == ["install"],
                "parent_id": p.get("parent_id") == "sec-1",
                "children": p.get("children") == ["child-1"],
                "wiki_structure_id": str(p.get("wiki_structure_id")) == structure_id,
            }
            bad = [k for k, v in checks.items() if not v]
            if bad:
                print(f"{FAIL} get_by_project 字段异常: {bad} -> {p}")
                all_ok = False
            else:
                print(f"{PASS} WikiPageRepository.get_by_project 字段齐全且正确")
        else:
            print(f"{FAIL} get_by_project 未返回页面")
            all_ok = False

        slug_row = WikiPageRepository.get_by_slug(test_project_id, "intro")
        if slug_row and slug_row.get("title") == "Intro":
            print(f"{PASS} WikiPageRepository.get_by_slug 命中")
        else:
            print(f"{FAIL} get_by_slug 异常: {slug_row}")
            all_ok = False

    except Exception as e:
        print(f"{FAIL} Repository 冒烟抛异常: {type(e).__name__}: {e}")
        all_ok = False

    finally:
        # --- 清理测试数据 ---
        try:
            WikiPageRepository.delete_by_project(test_project_id)
            WikiStructureRepository.delete_by_project(test_project_id)
            sync_conn.execute("DELETE FROM projects WHERE id = %s", (test_project_id,))
            print(f"\n[清理] 测试数据已删除 (project_id={test_project_id})")
        except Exception as e:
            print(f"[清理] 清理失败: {e}")

    return all_ok


# ---------------------------------------------------------------------------

async def main():
    ok_schema = await probe_schema()
    ok_repo = smoke_repository()

    print("\n" + "=" * 56)
    print(f"结构探测: {'通过' if ok_schema else '失败'}")
    print(f"Repository 冒烟: {'通过' if ok_repo else '失败'}")
    print("=" * 56)
    sys.exit(0 if (ok_schema and ok_repo) else 1)


if __name__ == "__main__":
    asyncio.run(main())
