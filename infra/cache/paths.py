"""
infra.cache.paths — Wiki 缓存路径（缓存基础设施职责）
====================================================

Wiki 缓存结果（最终持久化产物）的统一存放目录。

从 core.config 下沉至此，使缓存路径归属于缓存层，消除 infra → core 的反向依赖。
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

WIKI_CACHE_DIR = os.path.join(get_adalflow_default_root_path(), "wikicache")
os.makedirs(WIKI_CACHE_DIR, exist_ok=True)
