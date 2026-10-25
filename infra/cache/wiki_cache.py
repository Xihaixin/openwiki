"""
Wiki 缓存 — Redis + PostgreSQL 双层缓存

采用 Cache-Aside 模式：
- 读：先查 Redis（整包 payload）→ 未命中则由 PostgreSQL 重建并回填
- 写：先写 PostgreSQL（持久化）→ 再覆盖写 Redis（整包 payload）
- 删：软删除 PostgreSQL 数据 → 同时删除 Redis 键

Redis key 格式:
  wiki:cache:{project_id}:{language}:c{0|1}       — 整包 Wiki payload（结构 + 全部页面）

数据契约（WikiCacheData 等价结构）：
  read/save 以 JSON 可序列化 dict 交互，结构校验由 core.services.wiki_cache 负责。
"""

import json
import logging
from typing import Any, Dict, List, Optional

from infra.cache.redis_client import redis_client
from core.models.repository import (
    ProjectRepository,
    WikiStructureRepository,
    WikiPageRepository,
)

logger = logging.getLogger(__name__)


# Redis key 前缀
CACHE_PREFIX = "wiki:cache"

# 默认 TTL（秒）：7 天
DEFAULT_TTL = 7 * 24 * 3600


def _mode_suffix(comprehensive: bool) -> str:
    """comprehensive 维度后缀（Redis key 区分 concise/comprehensive 两套缓存）"""
    return "c1" if comprehensive else "c0"


class WikiCacheManager:
    """Wiki 双层缓存管理器（Redis + PostgreSQL）"""

    # ── 内部 key 构建 ──────────────────────────────────────────────

    @staticmethod
    def _cache_key(project_id: str, language: str, comprehensive: bool = False) -> str:
        return f"{CACHE_PREFIX}:{project_id}:{language}:{_mode_suffix(comprehensive)}"

    # ── 读操作：Cache-Aside ────────────────────────────────────────

    def get_cache(self, project_id: str, language: str,
                  comprehensive: bool = False) -> Optional[dict]:
        """获取整包 Wiki 缓存（仅 Redis；未命中时由上层从 PostgreSQL 重建）"""
        redis_key = self._cache_key(project_id, language, comprehensive)
        cached = redis_client.get(redis_key)

        if isinstance(cached, dict):
            logger.debug(f"Wiki cache HIT (Redis): {project_id}/{language}/{comprehensive}")
            return cached

        if cached is not None:
            # 命中但结构非法：删除脏值，交由上层重建
            logger.warning(f"Invalid wiki cache dropped: {redis_key}")
            redis_client.delete(redis_key)

        logger.debug(f"Wiki cache MISS (Redis): {project_id}/{language}/{comprehensive}")
        return None

    def save_cache(self, payload: dict, project_id: str, language: str, comprehensive: bool=False):
        """这个函数直接缓存前端传过来的 payload 所包含的全部内容: wiki_structure 和 wiki_pages"""
        redis_key = self._cache_key(project_id, language, comprehensive)
        
        try:
            result = redis_client.set(
                redis_key, 
                json.dumps(payload, ensure_ascii=False, default=str), 
                ttl=DEFAULT_TTL)

            return result
        except Exception as e:
            logger.warning(f"Failed to save the payload cache: {e}")
            return False

    # ── 写操作：先写 PostgreSQL，再写 Redis ────────────────────────

    # ── 写操作：先写 PostgreSQL，再写 Redis ────────────────────────

    def save_wiki_structure(
        self,
        project_id: str,
        language: str,
        structure_json: dict,
        comprehensive: bool = False,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> str:
        """保存 Wiki 结构（PostgreSQL → Redis），按 comprehensive 维度区分"""
        # 1. 先写 PostgreSQL
        record_id = WikiStructureRepository.upsert(
            project_id=project_id,
            language=language,
            structure_json=structure_json,
            is_comprehensive=comprehensive,
            provider=provider,
            model=model,
        )

        # Redis 不再单独缓存 structure，统一由 save() 写入整包 payload
        return record_id

    def save_wiki_page(
        self,
        project_id: str,
        page_slug: str,
        title: str,
        content_md: str,
        wiki_structure_id: Optional[str] = None,
        file_paths: Optional[List[str]] = None,
        importance: str = "medium",
        related_pages: Optional[List[str]] = None,
        parent_id: Optional[str] = None,
        is_section: bool = False,
        children: Optional[List[str]] = None,
        source_chunks: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """保存单个 Wiki 页面（PostgreSQL → Redis）"""
        # 1. 先写 PostgreSQL
        page_id = WikiPageRepository.upsert(
            project_id=project_id,
            page_slug=page_slug,
            title=title,
            content_md=content_md,
            wiki_structure_id=wiki_structure_id,
            file_paths=file_paths,
            importance=importance,
            related_pages=related_pages,
            parent_id=parent_id,
            is_section=is_section,
            children=children,
            source_chunks=source_chunks,
        )

        # Redis 不再单独缓存页面，统一由 save() 写入整包 payload
        return page_id

    # ── 删操作：软删除 PostgreSQL + 删除 Redis ─────────────────────

    def delete_cache(self, project_id: str, language: str) -> bool:
        """删除 Wiki 缓存（PostgreSQL 软删除 + Redis，删除该语言下所有 comprehensive 变体）"""
        # 1. 删除 Redis（按语言前缀匹配全部变体）
        try:
            keys = redis_client.scan(f"{CACHE_PREFIX}:{project_id}:{language}:*")
            for key in keys or []:
                redis_client.delete(key)
        except Exception as e:
            logger.debug(f"Failed to delete Redis cache: {e}")

        # 2. PostgreSQL 软删除
        result = WikiStructureRepository.delete(project_id, language)

        return result


# 全局单例
wiki_cache_manager = WikiCacheManager()


class WikiCacheStorage:
    """PostgreSQL 持久化 + Redis 运行期缓存实现。

    说明：
    - `wiki_structure` / `wiki_pages` 表保存的是**最终生成的 Wiki 页面与结构**
      （持久化结果），Redis 仅作为运行期热缓存。
    - 通过 (owner, repo, repo_type) 解析 project_id（不存在时按需创建项目记录，
      与 core/flows/wiki_flow.py 的 get_or_create 行为一致）。
      （wiki_structure / generated_pages / repo / provider / model），
      页面从 wiki_pages 表按 (project_id, page_slug) 组装，
      language/is_comprehensive 收敛到结构级。
    """

    def __init__(self, manager: Optional[WikiCacheManager] = None):
        self._manager = manager or wiki_cache_manager

    # ── 内部辅助 ──────────────────────────────────────────────

    def _resolve_project_id(
        self, owner: str, repo: str, repo_type: str,
    ) -> Optional[str]:
        """将 (owner, repo, repo_type) 解析为 project_id"""
        project = ProjectRepository.find(
            name=repo, owner=owner, repo_type=repo_type,
        )
        return str(project["id"]) if project else None

    @staticmethod
    def _build_generate_pages(pages: Optional[List] | None):
        generated_pages:Dict[str, Any] = {}

        if pages is not None:
            for p in pages:
                # 统一字段映射：DB 行为 page_slug/content_md/file_paths/...，
                # 前端结构为 id/content/filePaths/...（camelCase）
                slug = p.get("page_slug") or p.get("id")
                if not slug:
                    continue
                generated_pages[slug] = {
                    "id": slug,
                    "title": p.get("title", slug),
                    "content": p.get("content_md") or "",
                    "filePaths": p.get("filePaths") or p.get("file_paths") or [],
                    "importance": p.get("importance") or "medium",
                    "relatedPages": p.get("relatedPages") or p.get("related_pages") or [],
                    "parentId": p.get("parentId") or p.get("parent_id"),
                    "isSection": p.get("isSection") or p.get("is_section", False),
                    "children": p.get("children") or [],
                }
        return generated_pages

    @staticmethod
    def _build_payload(
        project_id: str, 
        language: str='zh',
        comprehensive: bool=False
        ) -> Optional[Dict[str, Any]]:
        """将 wiki_structure 记录 + wiki_pages 列表组装为完整 payload（WikiCacheData 等价 dict）。

        这里只做组装与最基本的完整性检查；严格契约校验由 core.services.wiki_cache 负责。
        """
        wiki_data = WikiStructureRepository.get_structure_and_pages(project_id, language, comprehensive)
        if not wiki_data:
            return None

        pages = wiki_data.get('pages')
        repo_data = wiki_data.get('repo') or {}
        structure_data = wiki_data.get('structure') or {}
        structure_json = structure_data.get('structure_json')

        if not structure_json:
            logger.error(
                "wiki_structure_json missing, skip payload rebuild: project=%s lang=%s",
                project_id, language
            )
            return None

        generated_pages = WikiCacheStorage._build_generate_pages(pages)   # type: ignore

        # structure_json.pages 必须保持为 list（前端 WikiStructureModel.pages 为 List[WikiPage]，
        # 用于 find/map/length 遍历）；generated_pages 才是 Dict[str, WikiPage]（按 slug 取正文）。
        structure_json["pages"] = list(generated_pages.values())

        return {
            "project_id": project_id,
            "language": language,
            "comprehensive": comprehensive,
            "wiki_structure": structure_json,
            "generated_pages": generated_pages,
            "repo": {
                "projectId": project_id,
                "owner": repo_data.get("owner"),
                "repo": repo_data.get("name"),
                "type": repo_data.get("repo_type"),
                "repoUrl": repo_data.get("repo_url"),
            },
            "repo_url": repo_data.get("repo_url"),
            "provider": structure_data.get("provider"),
            "model": structure_data.get("model"),
        }

    # ── 接口实现 ──────────────────────────────────────────────

    def read(
        self,
        id: str,
        owner: str,
        repo: str,
        repo_type: str,
        language: str,
        comprehensive: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """读取已生成 Wiki（Redis → PostgreSQL），返回完整 payload"""

        project_id = id or self._resolve_project_id(owner, repo, repo_type)

        if not project_id:
            return None
        
        payload = self._manager.get_cache(project_id, language, comprehensive)

        if payload:
            return payload
        
        payload = self._build_payload(project_id, language, comprehensive)
        
        if not payload:
            return None
        
        if self._manager.save_cache(payload, project_id, language, comprehensive):
            logger.debug(f"Wiki payload backfilled: {project_id}/{language}")
        else:
            logger.warning(f"Wiki payload backfill failed: {project_id}/{language}")

        return payload

    def save(
        self,
        payload: Dict[str, Any],
    ) -> bool:
        """
        保存已生成 Wiki 数据（PostgreSQL → Redis），含 structure + 全部页面，直接保存 payload
        redis 默认情况下，不再分别缓存 structure 和 pages。

        """
        repo_info = payload.get("repo") or {}
        owner = repo_info.get("owner", "")
        repo = repo_info.get("repo", "")
        # wiki_structure.repo_type 为 NOT NULL，兜底为 github
        repo_type = repo_info.get("type") or "github"
        wiki_pages = payload.get("generated_pages") or None

        if wiki_pages is None:
            logger.debug(f"The payload can't find wiki pages.")
            return False
        
        if payload.get("project_id",""):
            project_id = payload.get("project_id","")
        else:
            project_id = self._resolve_project_id(owner, repo, repo_type)

        if not project_id:
            return False
        
        structure_json = payload.get("wiki_structure") or {}
        language = payload.get("language", "zh")
        comprehensive = payload.get("comprehensive", False)

        try:
            ## 1. 保存 wiki_structure（结构 + 元数据）
            record_id = self._manager.save_wiki_structure(
                project_id=project_id,
                language=language,
                structure_json=structure_json,
                comprehensive=comprehensive,
                provider=payload.get("provider"),
                model=payload.get("model"),
            )
            logger.debug(f"The WikiStructure's RecordId is {record_id}.")

            ## 2. 遍历 generated_pages，逐页写入 wiki_pages（内容 + 树定位字段）
            # BUG:包含 importance, related_pages, parent_id 在内的几个字段取不到值，好像一开始这些属性都藏在 wiki_structure 中
            # 后续重新构造的时候，似乎也只是用到了 wiki_page 表中的 slug 和 content_md 两个字段

            for page_slug, page_data in wiki_pages.items():
                if not isinstance(page_data, dict):
                    continue
                self._manager.save_wiki_page(
                    project_id=project_id,
                    page_slug=page_data.get("id") or page_slug,
                    title=page_data.get("title", page_slug),
                    content_md=page_data.get("content") or "",
                    wiki_structure_id=record_id,
                    file_paths=page_data.get("filePaths") or [],
                    importance=page_data.get("importance") or "medium",
                    related_pages=page_data.get("relatedPages") or [],
                    parent_id=page_data.get("parentId"),
                    is_section=page_data.get("isSection", False),
                    children=page_data.get("children") or [],
                )

            # 整包 payload 直接覆盖写入 Redis（structure + 全部页面）
            if not self._manager.save_cache(payload, project_id, language, comprehensive):
                logger.warning(
                    f"Wiki payload cache write failed: {project_id}/{language}"
                )

            return True
        except Exception as e:
            logger.error(f"Failed to save wiki cache to DB/Redis: {e}", exc_info=True)
            return False

    def delete(self, owner: str, repo: str, repo_type: str, language: str) -> bool:
        """删除指定 Wiki（PostgreSQL 软删除 + Redis）"""
        project_id = self._resolve_project_id(owner, repo, repo_type)
        if not project_id:
            return False
        return self._manager.delete_cache(project_id, language)

    def list_projects(self, default_language: str = "en") -> List[Dict[str, Any]]:
        """列出所有已初始化项目及其 Wiki 变体，字段对齐 ProcessedProjectEntry 契约。

        项目身份与变体维度由 ProjectRepository.list_processed 一次查询返回，
        本方法只做契约转换（展示名拼接、时间戳毫秒化）。
        """
        rows = ProjectRepository.list_processed(default_language)
        projects: List[Dict[str, Any]] = []
        for r in rows:
            proj_id = str(r.get("id") or "")
            if not proj_id:
                logger.warning("skip row without project id: %r", r)
                continue

            owner = r.get("owner") or ""
            repo = r.get("repo") or ""
            projects.append(
                {
                    "id": proj_id,
                    "owner": owner,
                    "repo": repo,
                    "name": f"{owner}/{repo}".strip("/") or proj_id,
                    "repo_type": r.get("repo_type") or "github",
                    "submittedAt": _to_ms(r.get("created_at")),
                    "language": r.get("language") or default_language,
                    "comprehensive": bool(r.get("comprehensive")),
                }
            )
        return projects


def _to_ms(value: Any) -> int:
    """将 datetime 转毫秒时间戳（文件系统实现的 submittedAt 单位为 ms）"""
    if value is None:
        return 0
    try:
        return int(value.timestamp() * 1000)
    except (AttributeError, ValueError, TypeError):
        try:
            return int(value)
        except (ValueError, TypeError):
            return 0

