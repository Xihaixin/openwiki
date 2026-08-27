"""openwiki 数据库迁移执行器。

用法（在项目根目录、使用 .venv 的 python 执行）：
    python -m infra.migration.runner --create openwiki      # 创建数据库（幂等）
    python -m infra.migration.runner --db openwiki          # 应用未执行的迁移
    python -m infra.migration.runner --db openwiki --reset  # 重建 public schema 后全量应用
    python -m infra.migration.runner --db openwiki --list   # 列出迁移状态

迁移脚本约定：
    - 每个数据库对应 infra/migration/scripts/<db>/ 目录
    - 脚本命名 NNN_<description>.sql，按文件名顺序应用
    - 每个脚本在单个事务中执行，失败整体回滚
    - 已应用版本记录在目标库的 schema_migrations 表

连接参数从环境变量读取（.env 或系统环境）：
    PGHOST / PGPORT / PGUSER / PGPASSWORD
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv()

SCRIPTS_DIR = Path(__file__).resolve().parent / "scripts"

VERSION_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

# Windows 下常见 locale 候选（按优先级尝试，成功即止）
LOCALE_CANDIDATES = [
    "Chinese (Simplified)_China.936",
    "en_US.UTF-8",
    "zh_CN.UTF-8",
    "C",
]


def _conn_kwargs(database: str) -> dict:
    return {
        "host": os.getenv("PGHOST", "localhost"),
        "port": int(os.getenv("PGPORT", "5432")),
        "dbname": database,
        "user": os.getenv("PGUSER", "postgres"),
        "password": os.getenv("PGPASSWORD", "postgres"),
    }


def create_database(name: str) -> bool:
    """连接 postgres 维护库创建目标数据库（幂等）。

    Windows 上 template1 的 locale/encoding 可能与 UTF8 冲突，因此按候选
    locale 列表逐个尝试（TEMPLATE template0 + 显式 UTF8）。
    """
    conn = psycopg2.connect(**_conn_kwargs("postgres"))
    conn.autocommit = True
    cur = conn.cursor()
    try:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
        if cur.fetchone():
            print(f"[SKIP] database '{name}' already exists")
            return True

        # 获取 template1 的 locale，作为首选候选
        cur.execute(
            "SELECT datcollate, datctype FROM pg_database WHERE datname = 'template1'"
        )
        row = cur.fetchone()
        candidates = [c for c in (row or ()) if c] + LOCALE_CANDIDATES

        last_err: Exception | None = None
        for collate in candidates:
            try:
                cur.execute(
                    f'CREATE DATABASE "{name}" TEMPLATE template0 ENCODING \'UTF8\' '
                    f'LC_COLLATE=%s LC_CTYPE=%s',
                    (collate, collate),
                )
                print(f"[OK] database '{name}' created (locale={collate})")
                return True
            except psycopg2.Error as e:  # 每个候选失败，继续尝试
                last_err = e
                conn.rollback()

        print(f"[FAIL] create database '{name}': {last_err}")
        return False
    finally:
        cur.close()
        conn.close()


def _get_applied(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(VERSION_TABLE_DDL)
        conn.commit()
        cur.execute("SELECT version FROM schema_migrations")
        return {r[0] for r in cur.fetchall()}


def apply_migrations(database: str, reset: bool = False, list_only: bool = False) -> bool:
    script_dir = SCRIPTS_DIR / database
    scripts = sorted(script_dir.glob("*.sql")) if script_dir.is_dir() else []
    if not scripts:
        print(f"[FAIL] no migration scripts found in {script_dir}")
        return False

    conn = psycopg2.connect(**_conn_kwargs(database))

    if reset:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA public CASCADE")
            cur.execute("CREATE SCHEMA public")
            cur.execute("GRANT ALL ON SCHEMA public TO public")
        conn.autocommit = False
        print("[OK] public schema reset")

    applied = _get_applied(conn)

    if list_only:
        print(f"\nMigration status for database '{database}':")
        for path in scripts:
            version = path.stem.split("_", 1)[0]
            mark = "APPLIED" if version in applied else "PENDING"
            print(f"  [{mark:7s}] {path.name}")
        print()
        conn.close()
        return True

    ok = True
    for path in scripts:
        version = path.stem.split("_", 1)[0]
        if version in applied:
            print(f"[SKIP] {path.name}")
            continue
        print(f"[RUN ] {path.name} ...", end="", flush=True)
        try:
            with conn.cursor() as cur:
                cur.execute(path.read_text(encoding="utf-8"))
                cur.execute(
                    "INSERT INTO schema_migrations (version, name) VALUES (%s, %s)",
                    (version, path.name),
                )
            conn.commit()
            print(" OK")
        except Exception as e:
            conn.rollback()
            print(f" FAILED: {e}")
            ok = False

    conn.close()
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="openwiki 数据库迁移执行器")
    parser.add_argument("--create", metavar="DB", help="创建目标数据库（幂等）")
    parser.add_argument("--db", metavar="DB", help="目标数据库，应用迁移")
    parser.add_argument("--reset", action="store_true", help="重建 public schema 后全量应用")
    parser.add_argument("--list", action="store_true", help="仅列出迁移状态")
    args = parser.parse_args()

    if not args.create and not args.db:
        parser.print_help()
        return 1

    if args.create and not create_database(args.create):
        return 1
    if args.db:
        return 0 if apply_migrations(args.db, reset=args.reset, list_only=args.list) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
