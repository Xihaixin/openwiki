"""
infra.cache.paths — Wiki 缓存路径（缓存基础设施职责）
====================================================

Wiki 缓存结果（最终持久化产物）的统一存放目录。

从 core.config 下沉至此，使缓存路径归属于缓存层，消除 infra → core 的反向依赖。
"""

import os

from infra.config.paths import get_adalflow_default_root_path


WIKI_CACHE_DIR = os.path.join(get_adalflow_default_root_path(), "wikicache")
os.makedirs(WIKI_CACHE_DIR, exist_ok=True)
