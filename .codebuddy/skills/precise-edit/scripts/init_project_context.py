#!/usr/bin/env python3
"""初始化 precise-edit Skill 所需的项目专属目录结构。

幂等设计:已存在的文件一律跳过,绝不覆盖用户已有内容。

用法:
    python init_project_context.py                      # 根目录自动推断,日期取当前
    python init_project_context.py --root /path/to/proj
    python init_project_context.py --date 2026-08       # 指定年月
    python init_project_context.py --dry-run            # 只打印计划,不实际创建

产物:
    <root>/.codebuddy/project/{PROJECT,ARCHITECTURE,CONVENTIONS,LESSONS}.md
    <root>/.aidocs/task/
    <root>/.aidocs/<YYYY>/<MM>/
    <root>/.aidocs/openwiki/<YYYY>/<MM>/
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

# 脚本位于 <root>/.codebuddy/skills/precise-edit/scripts/,向上 4 级即项目根
DEFAULT_DEPTH = 4

TEMPLATES: dict[str, str] = {
    "PROJECT.md": """# 项目概况

> 由 precise-edit Skill 生成,请补充项目特有信息。

## 项目定位

<!-- 一句话说明项目是什么、解决什么问题 -->

## 技术栈

- 后端:
- 前端:
- 存储:
- 缓存:

## 关键入口

| 用途 | 路径 |
|---|---|
| 服务启动 | |
| CLI 入口 | |
| 迁移执行 | |

## 当前版本

""",
    "ARCHITECTURE.md": """# 架构与修改联动清单

> 由 precise-edit Skill 生成,请补充项目特有信息。

## 分层结构

<!-- 自顶向下列出各层职责与目录 -->

| 层 | 目录 | 职责 |
|---|---|---|
| | | |

## 依赖方向

<!-- 用箭头说明允许的依赖方向,并标注禁止的反向依赖 -->

## 修改联动清单

<!-- 改动 X 时必须同步检查 Y。这是精准修改最容易遗漏的地方,务必写全 -->

| 改动对象 | 必须同步检查 |
|---|---|
| | |

## 已知易错点

""",
    "CONVENTIONS.md": """# 编码约定

> 由 precise-edit Skill 生成,请补充项目特有信息。

## 命名风格

## 导入组织

## 类型注解

## 异步与同步

## 错误处理

## 日志

## 配置加载

## 测试

## 数据库与迁移

## 前端约定
""",
    "LESSONS.md": """# 长期技术约定

> 教训沉淀区。仅在用户显式要求复盘时追加。
> 条目格式见 `.codebuddy/skills/precise-edit/references/lessons-format.md`。
> 条目上限 50,超限后按触发频率精简。

## 活跃条目

<!-- - [YYYY-MM-DD] 【现象】...
  - 【根因】...
  - 【正确做法】...
  - 【触发场景】... -->

## 历史区

<!-- 长期未被触发的条目移入此处 -->
""",
}


def infer_root(script_path: Path) -> Path:
    """根据脚本位置向上推断项目根目录。"""
    resolved = script_path.resolve()
    if len(resolved.parents) > DEFAULT_DEPTH:
        return resolved.parents[DEFAULT_DEPTH]
    return Path.cwd()


def parse_date(value: str | None) -> tuple[str, str]:
    """解析 YYYY-MM 格式的日期参数,缺省取当前日期。"""
    if value is None:
        now = datetime.now()
        return f"{now.year:04d}", f"{now.month:02d}"
    match = re.fullmatch(r"(\d{4})-(\d{2})", value.strip())
    if not match:
        raise ValueError(f"--date 格式应为 YYYY-MM,收到:{value!r}")
    year, month = match.groups()
    if not 1 <= int(month) <= 12:
        raise ValueError(f"月份超出范围:{month}")
    return year, month


def ensure_dir(path: Path, created: list[str], skipped: list[str], dry_run: bool) -> None:
    if path.exists():
        skipped.append(f"目录已存在 {path}")
        return
    created.append(f"创建目录 {path}")
    if not dry_run:
        path.mkdir(parents=True, exist_ok=True)


def ensure_file(
    path: Path, content: str, created: list[str], skipped: list[str], dry_run: bool
) -> None:
    if path.exists():
        skipped.append(f"文件已存在 {path}")
        return
    created.append(f"创建文件 {path}")
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="初始化 precise-edit Skill 的项目专属目录结构"
    )
    parser.add_argument(
        "--root",
        default=None,
        help="项目根目录,缺省时根据脚本位置自动推断",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="归档年月,格式 YYYY-MM,缺省取当前日期",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印计划,不实际创建",
    )
    args = parser.parse_args()

    try:
        year, month = parse_date(args.date)
    except ValueError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 2

    root = Path(args.root).resolve() if args.root else infer_root(Path(__file__))

    created: list[str] = []
    skipped: list[str] = []

    # 项目专属上下文
    project_dir = root / ".codebuddy" / "project"
    ensure_dir(project_dir, created, skipped, args.dry_run)
    for filename, content in TEMPLATES.items():
        ensure_file(project_dir / filename, content, created, skipped, args.dry_run)

    # 任务定义目录
    ensure_dir(root / ".aidocs" / "task", created, skipped, args.dry_run)

    # 设计方案目录(年/月两层)
    ensure_dir(root / ".aidocs" / year / month, created, skipped, args.dry_run)

    # 过程总结目录
    ensure_dir(
        root / ".aidocs" / "openwiki" / year / month, created, skipped, args.dry_run
    )

    prefix = "[预演] " if args.dry_run else ""
    print(f"{prefix}项目根目录:{root}")
    print(f"{prefix}归档年月  :{year}/{month}")
    print(f"{prefix}创建 {len(created)} 项,跳过 {len(skipped)} 项")
    for line in created:
        print(f"  + {line}")
    for line in skipped:
        print(f"  = {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
