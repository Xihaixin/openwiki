"""
infra.config.paths — 数据根路径配置（基础设施层职责）
======================================================

集中管理项目数据文件的根目录计算逻辑：
  - ADALFLOW_DIR — 用户自定义的数据根目录环境变量
  - get_adalflow_default_root_path() — 按平台推导默认数据根目录

从 core.config 下沉至此，消除 infra → core 的反向依赖。
"""

import os
import sys


ADALFLOW_DIR = os.environ.get("ADALFLOW_DIR")


def get_adalflow_default_root_path() -> str:
    """获取 Adalflow 默认根路径"""
    platform = sys.platform
    if ADALFLOW_DIR:
        project_path = ADALFLOW_DIR
    elif platform == "win32":
        project_path = os.environ.get('LOCALAPPDATA', os.path.expanduser('~\\AppData\\Local'))
    elif platform == "adarwin":
        project_path = os.path.join(os.path.expanduser('~'), 'Library')
    else:
        # Linux/Unix: ~/.cache/
        # 遵循 XDG Base Directory Specification
        project_path = os.environ.get('XDG_CACHE_HOME', os.path.expanduser('~/.cache'))
    return os.path.expanduser(os.path.join(project_path, ".adalflow"))
