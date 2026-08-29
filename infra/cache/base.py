"""
Wiki 数据存储抽象接口

设计背景：
- `wiki_caches` / `wiki_pages` 表存储的是**最终生成的 Wiki 页面与结构**，
  属于持久化结果，而非可丢弃的中间产物。
- Redis 仅作为应用运行过程中"生成 Wiki / 加载历史 Wiki"的**运行期缓存**。

因此存储层抽象为 `WikiCacheStorage` 接口，当前提供两种实现：
- `FileSystemWikiCacheStorage`（infra.cache.filesystem）：文件系统，当前默认，行为向后兼容
- `DbRedisWikiCacheStorage`（infra.cache.wiki_cache）：PostgreSQL 持久化 + Redis 运行期缓存，生产形态

调用方（api / core.flows）只依赖此接口，通过配置或 DI 选择实现。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class WikiCacheStorage(Protocol):
    """Wiki 数据存储接口（统一以 JSON 可序列化 dict 作为数据契约）"""

    def read(
        self,
        owner: str,
        repo: str,
        repo_type: str,
        language: str,
        comprehensive: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """读取已生成的 Wiki（结构 + 页面）。未命中返回 None。"""
        ...

    def save(
        self,
        payload: Dict[str, Any],
        language: str,
        comprehensive: bool = False,
    ) -> bool:
        """保存已生成的 Wiki。

        payload 为 WikiCacheData 等价 dict（含 wiki_structure / generated_pages /
        repo / provider / model）。language / comprehensive 用于定位存储条目。
        """
        ...

    def delete(self, owner: str, repo: str, repo_type: str, language: str) -> bool:
        """删除指定 Wiki。返回是否确实删除了内容。"""
        ...

    def list_projects(self) -> List[Dict[str, Any]]:
        """列出所有已处理项目（含 id/owner/repo/name/repo_type/submittedAt/language/comprehensive）。"""
        ...
