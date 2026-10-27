"""
core.services.wiki_cache — Wiki 缓存业务服务
=============================================

对外提供 Wiki 缓存（最终持久化结果）的读写删与已处理项目列表能力，
屏蔽底层存储实现细节，并在此处统一做 payload 契约校验。

设计要点：
  - 上层（api）只依赖本服务，不直接接触 infra 存储层（避免跳跃依赖）
  - 存储形态固定为 PostgreSQL 持久化 + Redis 运行期缓存
  - 读/写均经 WikiCacheData 校验，避免非法结构进入 Redis 或返回给前端

依赖：
  - infra.cache.wiki_cache — PostgreSQL + Redis 双层缓存实现
  - core.models.schemas.WikiCacheData — 缓存 payload 的契约模型
"""

import logging
from typing import Any, Dict, List, Optional

from core.models.schemas import WikiCacheData
from infra.cache.wiki_cache import WikiCacheStorage

logger = logging.getLogger(__name__)


def _validate(payload: Dict[str, Any]) -> bool:
    """按 WikiCacheData 契约校验 payload，避免非法结构进入缓存。"""
    try:
        WikiCacheData(**payload)
        return True
    except Exception as e:
        logger.error(f"payload does not match WikiCacheData: {e}")
        return False


class WikiCacheService:
    """Wiki 数据存储与缓存业务服务"""

    def __init__(self, storage: Optional[WikiCacheStorage] = None):
        self._storage = storage or WikiCacheStorage()

    # ── 缓存 CRUD ──────────────────────────────────────────────

    def read(
        self,
        id: str,
        owner: str,
        repo: str,
        repo_type: str,
        language: str,
        comprehensive: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """读取已生成的 Wiki（结构 + 页面）。未命中或结构非法返回 None。"""
        payload = self._storage.read(id, owner, repo, repo_type, language, comprehensive)
        if not payload:
            return None

        if not _validate(payload):
            logger.error(
                f"drop invalid wiki payload: project={payload.get('project_id')} "
                f"lang={payload.get('language')}"
            )
            return None

        return payload

    def save(
        self,
        payload: Dict[str, Any],
    ) -> bool:
        """保存已生成的 Wiki。返回是否保存成功。"""
        if not _validate(payload):
            return False

        return self._storage.save(payload)

    def delete(self, owner: str, repo: str, repo_type: str, language: str) -> bool:
        """删除指定 Wiki。返回是否确实删除了内容。"""
        return self._storage.delete(owner, repo, repo_type, language)

    # ── 已处理项目列表 ─────────────────────────────────────────

    def list_projects(self, default_language: str = "en") -> List[Dict[str, Any]]:
        """列出所有已初始化项目（含尚未生成 Wiki 的项目）及其变体维度。"""
        return self._storage.list_projects(default_language)
