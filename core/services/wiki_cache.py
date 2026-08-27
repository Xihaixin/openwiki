"""
core.services.wiki_cache — Wiki 缓存业务服务
=============================================

对外提供 Wiki 缓存（最终持久化结果）的读写删与已处理项目列表能力，
屏蔽底层存储实现（文件系统 / PG+Redis）细节。

设计要点：
  - 上层（api）只依赖本服务，不直接接触 infra 存储层（避免跳跃依赖）
  - 默认使用文件系统实现，行为向后兼容
  - 切换为 PG+Redis 生产形态只需替换 storage 实例（如 CACHE_BACKEND 配置）

依赖：
  - infra.cache.base       — WikiCacheStorage 抽象接口
  - infra.cache.filesystem — 文件系统实现（当前默认）
  - infra.db.repository    — 项目仓库数据访问
"""

from typing import Any, Dict, List, Optional

from infra.cache.base import WikiCacheStorage
from infra.cache.filesystem import FileSystemWikiCacheStorage
from infra.db.repository import ProjectRepository


class WikiCacheService:
    """Wiki 缓存业务服务"""

    def __init__(self, storage: Optional[WikiCacheStorage] = None):
        # 默认文件系统实现（行为向后兼容）；生产形态切换为 DbRedisWikiCacheStorage()
        self._storage = storage or FileSystemWikiCacheStorage()

    # ── 缓存 CRUD ──────────────────────────────────────────────

    def read(
        self,
        owner: str,
        repo: str,
        repo_type: str,
        language: str,
        comprehensive: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """读取已生成的 Wiki（结构 + 页面）。未命中返回 None。"""
        return self._storage.read(owner, repo, repo_type, language, comprehensive)

    def save(
        self,
        payload: Dict[str, Any],
        language: str,
        comprehensive: bool = False,
    ) -> bool:
        """保存已生成的 Wiki。返回是否保存成功。"""
        return self._storage.save(payload, language=language, comprehensive=comprehensive)

    def delete(self, owner: str, repo: str, repo_type: str, language: str) -> bool:
        """删除指定 Wiki。返回是否确实删除了内容。"""
        return self._storage.delete(owner, repo, repo_type, language)

    # ── 已处理项目列表 ─────────────────────────────────────────

    def list_storage_projects(self) -> List[Dict[str, Any]]:
        """从存储层列出已处理项目（文件系统实现扫描缓存目录；DB 实现扫描 wiki_caches 表）。"""
        return self._storage.list_projects()

    def list_db_projects(self) -> List[Dict[str, Any]]:
        """从 PostgreSQL 数据库列出项目（作为补充来源）。"""
        return ProjectRepository.list_all()
