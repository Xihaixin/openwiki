"""
api.config — 向后兼容配置入口（委托给 core.config）
=======================================================

本文件是重构后的向后兼容入口，所有核心配置逻辑已迁移到:
  core/config/__init__.py

保留此文件以确保现有导入不受影响。
"""

import logging
from typing import Any, Dict, List, Optional

from core.config import (
    # 环境变量
    OPENAI_API_KEY,
    GOOGLE_API_KEY,
    OPENROUTER_API_KEY,
    DASHSCOPE_API_KEY,
    AWS_ACCESS_KEY_ID,
    AWS_SECRET_ACCESS_KEY,
    AWS_SESSION_TOKEN,
    AWS_REGION,
    AWS_ROLE_ARN,
    WIKI_AUTH_MODE,
    WIKI_AUTH_CODE,
    EMBEDDER_TYPE,
    CONFIG_DIR,

    # 配置加载函数
    replace_env_placeholders,
    load_json_config,
    load_generator_config,
    load_embedder_config,
    load_lang_config,
    load_repo_config,
    load_configs,

    # 默认排除列表
    DEFAULT_EXCLUDED_DIRS,
    DEFAULT_EXCLUDED_FILES,

    # 辅助函数
    get_embedder_config,
    get_embedder_type,
    get_model_config,
    get_config,
)

logger = logging.getLogger(__name__)

# ============================================================
# 全局配置缓存（单一来源：core.config，消除重复加载）
# ============================================================

configs: Dict[str, Any] = get_config()
