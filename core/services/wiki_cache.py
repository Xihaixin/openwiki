"""
core.services.wiki_cache — Wiki 缓存业务服务
=============================================

对外提供 Wiki 缓存（最终持久化结果）的读写删与已处理项目列表能力，
屏蔽底层存储实现细节。

设计要点：
  - 上层（api）只依赖本服务，不直接接触 infra 存储层（避免跳跃依赖）
  - 存储形态固定为 PostgreSQL 持久化 + Redis 运行期缓存

依赖：
  - infra.cache.wiki_cache — PostgreSQL + Redis 双层缓存实现
  - core.models.repository — 项目仓库数据访问
"""

from typing import Any, Dict, List, Optional

from infra.cache.wiki_cache import WikiCacheStorage


class WikiCacheService:
    """Wiki 数据存储与缓存业务服务"""

    def __init__(self, storage: Optional[WikiCacheStorage] = None):
        self._storage = storage or WikiCacheStorage()

    # ── 缓存 CRUD ──────────────────────────────────────────────

    def read(
        self,
        id:str,
        owner: str,
        repo: str,
        repo_type: str,
        language: str,
        comprehensive: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """读取已生成的 Wiki（结构 + 页面）。未命中返回 None。"""
        return self._storage.read(id, owner, repo, repo_type, language, comprehensive)

    def save(
        self,
        payload: Dict[str, Any],
    ) -> bool:
        """保存已生成的 Wiki。返回是否保存成功。"""
        return self._storage.save(payload)

    def delete(self, owner: str, repo: str, repo_type: str, language: str) -> bool:
        """删除指定 Wiki。返回是否确实删除了内容。"""
        return self._storage.delete(owner, repo, repo_type, language)

    def list_projects(self, default_language: str = "en") -> List[Dict[str, Any]]:
        """列出所有已初始化项目（含尚未生成 Wiki 的项目）及其变体维度。"""
        return self._storage.list_projects(default_language)
