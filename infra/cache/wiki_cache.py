"""
Wiki 缓存 — Redis + PostgreSQL 双层缓存

采用 Cache-Aside 模式：
- 读：先查 Redis（热缓存）→ 未命中则查 PostgreSQL → 回填 Redis
- 写：先写 PostgreSQL（持久化）→ 再写/更新 Redis
- 删：软删除 PostgreSQL 数据 → 同时删除 Redis 键

Redis key 格式:
  wiki:cache:{project_id}:{language}:c{0|1}       — Wiki 结构 + 元数据（按 comprehensive 区分）
  wiki:page:{project_id}:{page_slug}:{language}:c{0|1} — 单个 Wiki 页面
  wiki:projects:list                              — 已处理项目列表（缓存）

数据契约（与 infra/cache/base.py WikiCacheStorage 一致）：
  read/save 以 JSON 可序列化 dict（WikiCacheData 等价结构）交互，
  与 FileSystemWikiCacheStorage 的持久化格式保持兼容。
"""

import json
import logging
from typing import Any, Dict, List, Optional

from infra.cache.redis_client import redis_client
from infra.config.settings import settings
from infra.db.repository import (
    ProjectRepository,
    WikiCacheRepository,
    WikiPageRepository,
)

logger = logging.getLogger(__name__)


# Redis key 前缀
CACHE_PREFIX = "wiki:cache"
PAGE_PREFIX = "wiki:page"
PROJECTS_KEY = "wiki:projects:list"

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

    @staticmethod
    def _page_key(project_id: str, page_slug: str, language: str,
                  is_comprehensive: bool = True) -> str:
        return f"{PAGE_PREFIX}:{project_id}:{page_slug}:{language}:{_mode_suffix(is_comprehensive)}"

    # ── 读操作：Cache-Aside ────────────────────────────────────────

    def get_cache(self, project_id: str, language: str,
                  comprehensive: bool = False) -> Optional[dict]:
        """获取 Wiki 缓存（Redis → PostgreSQL），按 comprehensive 维度区分"""
        # 1. 先查 Redis
        redis_key = self._cache_key(project_id, language, comprehensive)
        cached = redis_client.get(redis_key)
        if cached is not None:
            try:
                data = json.loads(str(cached))
                logger.debug(f"Wiki cache HIT (Redis): {project_id}/{language}/{comprehensive}")
                return data
            except (json.JSONDecodeError, TypeError):
                pass

        # 2. Redis 未命中，查 PostgreSQL
        record = WikiCacheRepository.get_by_project(project_id, language, comprehensive)
        if not record:
            return None

        # 3. 回填 Redis
        try:
            redis_client.set(redis_key, json.dumps(record, ensure_ascii=False, default=str), ttl=DEFAULT_TTL)
        except Exception as e:
            logger.debug(f"Failed to backfill Redis cache: {e}")

        logger.debug(f"Wiki cache MISS (Redis), loaded from DB: {project_id}/{language}/{comprehensive}")
        return record

    def get_page(self, project_id: str, page_slug: str, language: str,
                 is_comprehensive: bool = True) -> Optional[dict]:
        """获取单个 Wiki 页面（Redis → PostgreSQL），按 comprehensive 维度区分"""
        # 1. 先查 Redis
        redis_key = self._page_key(project_id, page_slug, language, is_comprehensive)
        cached = redis_client.get(redis_key)
        if cached is not None:
            try:
                data = json.loads(str(cached))
                logger.debug(f"Wiki page HIT (Redis): {page_slug}")
                return data
            except (json.JSONDecodeError, TypeError):
                pass

        # 2. Redis 未命中，查 PostgreSQL
        record = WikiPageRepository.get_by_slug(project_id, page_slug, language, is_comprehensive)
        if not record:
            return None

        # 3. 回填 Redis
        try:
            redis_client.set(redis_key, json.dumps(record, ensure_ascii=False, default=str), ttl=DEFAULT_TTL)
        except Exception as e:
            logger.debug(f"Failed to backfill Redis page cache: {e}")

        logger.debug(f"Wiki page MISS (Redis), loaded from DB: {page_slug}")
        return record

    # ── 写操作：先写 PostgreSQL，再写 Redis ────────────────────────

    def save_cache(
        self,
        project_id: str,
        language: str,
        structure_json: dict,
        comprehensive: bool = False,
        repo_owner: Optional[str] = None,
        repo_name: Optional[str] = None,
        repo_type: Optional[str] = None,
        repo_url: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> str:
        """保存 Wiki 缓存（PostgreSQL → Redis），按 comprehensive 维度区分"""
        # 1. 先写 PostgreSQL
        record_id = WikiCacheRepository.upsert(
            project_id=project_id,
            language=language,
            structure_json=structure_json,
            comprehensive=comprehensive,
            repo_owner=repo_owner,
            repo_name=repo_name,
            repo_type=repo_type,
            repo_url=repo_url,
            provider=provider,
            model=model,
        )

        # 2. 再写 Redis
        try:
            redis_key = self._cache_key(project_id, language, comprehensive)
            cache_data = {
                "id": record_id,
                "project_id": project_id,
                "language": language,
                "comprehensive": comprehensive,
                "structure_json": structure_json,
                "repo_owner": repo_owner,
                "repo_name": repo_name,
                "repo_type": repo_type,
                "repo_url": repo_url,
                "provider": provider,
                "model": model,
            }
            redis_client.set(redis_key, json.dumps(cache_data, ensure_ascii=False), ttl=DEFAULT_TTL)
        except Exception as e:
            logger.debug(f"Failed to update Redis cache: {e}")

        # 3. 清除项目列表缓存（强制下次重新加载）
        try:
            redis_client.delete(PROJECTS_KEY)
        except Exception:
            pass

        return record_id

    def save_page(
        self,
        project_id: str,
        page_slug: str,
        title: str,
        content_md: str,
        language: str = "zh",
        is_comprehensive: bool = True,
        wiki_cache_id: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        source_chunks: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """保存单个 Wiki 页面（PostgreSQL → Redis）"""
        # 1. 先写 PostgreSQL
        page_id = WikiPageRepository.upsert(
            project_id=project_id,
            page_slug=page_slug,
            title=title,
            content_md=content_md,
            language=language,
            is_comprehensive=is_comprehensive,
            wiki_cache_id=wiki_cache_id,
            provider=provider,
            model=model,
            source_chunks=source_chunks,
        )

        # 2. 再写 Redis
        try:
            redis_key = self._page_key(project_id, page_slug, language, is_comprehensive)
            page_data = {
                "id": page_id,
                "project_id": project_id,
                "page_slug": page_slug,
                "title": title,
                "content_md": content_md,
                "language": language,
                "is_comprehensive": is_comprehensive,
                "provider": provider,
                "model": model,
            }
            redis_client.set(redis_key, json.dumps(page_data, ensure_ascii=False), ttl=DEFAULT_TTL)
        except Exception as e:
            logger.debug(f"Failed to update Redis page cache: {e}")

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
        result = WikiCacheRepository.delete(project_id, language)

        # 3. 清除项目列表缓存
        try:
            redis_client.delete(PROJECTS_KEY)
        except Exception:
            pass

        return result

    def delete_project_cache(self, project_id: str):
        """删除项目的所有缓存（PostgreSQL 软删除 + Redis）"""
        # 1. 删除 Redis（按模式匹配）
        try:
            cache_keys = redis_client.scan(f"{CACHE_PREFIX}:{project_id}:*")
            page_keys = redis_client.scan(f"{PAGE_PREFIX}:{project_id}:*")
            for key in (cache_keys or []) + (page_keys or []):
                redis_client.delete(key)
        except Exception as e:
            logger.debug(f"Failed to delete Redis project keys: {e}")

        # 2. PostgreSQL 软删除
        WikiCacheRepository.delete_by_project(project_id)
        WikiPageRepository.delete_by_project(project_id)

        # 3. 清除项目列表缓存
        try:
            redis_client.delete(PROJECTS_KEY)
        except Exception:
            pass

    # ── 项目列表缓存 ──────────────────────────────────────────────

    def get_cached_projects(self) -> Optional[List[dict]]:
        """获取缓存的项目列表（Redis）"""
        cached = redis_client.get(PROJECTS_KEY)
        if cached is not None:
            try:
                return json.loads(str(cached))
            except (json.JSONDecodeError, TypeError):
                pass
        return None

    def set_cached_projects(self, projects: List[dict]):
        """缓存项目列表（Redis）"""
        try:
            redis_client.set(PROJECTS_KEY, json.dumps(projects, ensure_ascii=False, default=str), ttl=DEFAULT_TTL)
        except Exception as e:
            logger.debug(f"Failed to cache projects list: {e}")


# 全局单例
wiki_cache_manager = WikiCacheManager()


class DbRedisWikiCacheStorage:
    """PostgreSQL 持久化 + Redis 运行期缓存实现（WikiCacheStorage 接口）。

    说明：
    - `wiki_caches` / `wiki_pages` 表保存的是**最终生成的 Wiki 页面与结构**
      （持久化结果），Redis 仅作为运行期热缓存。
    - 通过 (owner, repo, repo_type) 解析 project_id（不存在时按需创建项目记录，
      与 core/flows/wiki_flow.py 的 get_or_create 行为一致）。
    - read 返回与 FileSystemWikiCacheStorage 一致的完整 payload
      （wiki_structure / generated_pages / repo / provider / model），
      页面从 wiki_pages 表按 (project_id, language, is_comprehensive) 组装。
    """

    def __init__(self, manager: Optional[WikiCacheManager] = None):
        self._manager = manager or wiki_cache_manager

    # ── 内部辅助 ──────────────────────────────────────────────

    def _resolve_project_id(
        self, owner: str, repo: str, repo_type: str,
    ) -> Optional[str]:
        """将 (owner, repo, repo_type) 解析为 project_id"""
        project = ProjectRepository.get_or_create(
            name=f"{owner}/{repo}", owner=owner, repo_type=repo_type,
        )
        return str(project["id"]) if project else None

    @staticmethod
    def _build_payload(record: dict, pages: List[dict]) -> Dict[str, Any]:
        """将 wiki_caches 记录 + wiki_pages 列表组装为完整 payload（WikiCacheData 等价 dict）"""
        structure_json = record.get("structure_json") or {}
        generated_pages: Dict[str, Any] = {}
        for p in pages:
            slug = p.get("page_slug") or p.get("id")
            if not slug:
                continue
            generated_pages[slug] = {
                "id": slug,
                "title": p.get("title", slug),
                "content": p.get("content_md", ""),
                "filePaths": [],
                "importance": "medium",
                "relatedPages": [],
            }
        repo_info = {
            "owner": record.get("repo_owner"),
            "repo": record.get("repo_name"),
            "type": record.get("repo_type"),
            "repoUrl": record.get("repo_url"),
        }
        return {
            "wiki_structure": structure_json,
            "generated_pages": generated_pages,
            "repo_url": record.get("repo_url"),
            "repo": repo_info,
            "provider": record.get("provider"),
            "model": record.get("model"),
            "language": record.get("language"),
            "comprehensive": record.get("comprehensive", False),
        }

    # ── 接口实现 ──────────────────────────────────────────────

    def read(
        self,
        owner: str,
        repo: str,
        repo_type: str,
        language: str,
        comprehensive: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """读取已生成 Wiki（Redis → PostgreSQL），返回完整 payload"""
        project_id = self._resolve_project_id(owner, repo, repo_type)
        if not project_id:
            return None
        record = self._manager.get_cache(project_id, language, comprehensive)
        if not record:
            return None
        pages = WikiPageRepository.get_by_project(
            project_id, language=language, is_comprehensive=comprehensive,
        )
        return self._build_payload(record, pages)

    def save(
        self,
        payload: Dict[str, Any],
        language: str,
        comprehensive: bool = False,
    ) -> bool:
        """保存已生成 Wiki（PostgreSQL → Redis），含 structure + 全部页面"""
        repo_info = payload.get("repo") or {}
        owner = repo_info.get("owner", "")
        repo = repo_info.get("repo", "")
        # wiki_caches.repo_type 为 NOT NULL，兜底为 github
        repo_type = repo_info.get("type") or "github"
        project_id = self._resolve_project_id(owner, repo, repo_type)
        if not project_id:
            return False
        structure_json = payload.get("wiki_structure") or {}
        try:
            record_id = self._manager.save_cache(
                project_id=project_id,
                language=language,
                structure_json=structure_json,
                comprehensive=comprehensive,
                repo_owner=owner or None,
                repo_name=repo or None,
                repo_type=repo_type,
                repo_url=repo_info.get("repoUrl") or repo_info.get("url"),
                provider=payload.get("provider"),
                model=payload.get("model"),
            )

            # 逐页持久化到 wiki_pages（带 wiki_cache_id 溯源）
            generated_pages = payload.get("generated_pages") or {}
            for slug, page in generated_pages.items():
                WikiPageRepository.upsert(
                    project_id=project_id,
                    page_slug=slug,
                    title=page.get("title", slug),
                    content_md=page.get("content", ""),
                    language=language,
                    is_comprehensive=comprehensive,
                    wiki_cache_id=record_id,
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

    def list_projects(self) -> List[Dict[str, Any]]:
        """列出所有已处理项目（wiki_caches 表），字段对齐 ProcessedProjectEntry 契约"""
        rows = WikiCacheRepository.list_all()
        projects: List[Dict[str, Any]] = []
        for r in rows:
            owner = r.get("repo_owner") or ""
            repo = r.get("repo_name") or ""
            projects.append(
                {
                    "id": r.get("project_id"),
                    "owner": owner,
                    "repo": repo,
                    "name": f"{owner}/{repo}".strip("/") or r.get("project_id"),
                    "repo_type": r.get("repo_type") or "github",
                    "submittedAt": _to_ms(r.get("created_at")),
                    "language": r.get("language"),
                    "comprehensive": r.get("comprehensive", False),
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


# 生产形态实例（切换入口：api 层配置 CACHE_BACKEND=db_redis 时使用）
db_redis_wiki_cache_storage = DbRedisWikiCacheStorage()
