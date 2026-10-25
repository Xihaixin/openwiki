"""
api.routers.wiki_cache — Wiki 缓存端点
======================================

缓存结果（Wiki 页面与结构）的查询、保存、删除，以及已处理项目列表。

存储层固定在 infra.cache.wiki_cache（PostgreSQL 持久化 + Redis 运行期缓存），
本模块仅通过 core.services.wiki_cache.WikiCacheService 访问。
"""

import asyncio
import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from core.config import WIKI_AUTH_CODE, WIKI_AUTH_MODE, configs
from api.models import (
    ProcessedProjectEntry,
    WikiCacheData,
    WikiCacheRequest,
)
from core.services.wiki_cache import WikiCacheService

logger = logging.getLogger(__name__)

router = APIRouter()

# Wiki 缓存业务服务（PostgreSQL 持久化 + Redis 运行期缓存）
wiki_cache_service = WikiCacheService()


# ============================================================
# Wiki 缓存 CRUD
# ============================================================


@router.get("/api/wiki_cache", response_model=Optional[WikiCacheData])
async def get_cached_wiki(
    projectId: str = Query(..., description="project id"),
    owner: str = Query(..., description="Repository owner"),
    repo: str = Query(..., description="Repository name"),
    repo_type: str = Query(..., description="Repository type (e.g., github, gitlab)"),
    language: str = Query(..., description="Language of the wiki content"),
    comprehensive: bool = Query(...,description="use comprehensive or not"),
):
    """获取缓存的 Wiki 数据"""
    supported_langs = configs.get("lang", {}).get("supported_languages", {})
    if language not in supported_langs:
        language = configs.get("lang", {}).get("default", "zh")

    logger.info(f"Retrieving wiki cache for {owner}/{repo} ({repo_type}), lang: {language}")
    cached_data = wiki_cache_service.read(projectId, owner, repo, repo_type, language, comprehensive)
    if cached_data:
        return WikiCacheData(**cached_data)
    else:
        if projectId:
            logger.info(f"Wiki cache not found for {projectId}")
            logger.info(f"The detail is: {owner}/{repo} ({repo_type}), lang: {language}")
            return None
        else:
            logger.info(f"The project id is null, check the application...")


@router.post("/api/wiki_cache")
async def store_wiki_cache(request_data: WikiCacheRequest):
    """存储 Wiki 缓存"""
    supported_langs = configs.get("lang", {}).get("supported_languages", {})
    if request_data.language not in supported_langs:
        request_data.language = configs.get("lang", {}).get("default", "en")

    logger.info(
        f"Saving wiki cache for {request_data.repo.owner}/{request_data.repo.repo} "
        f"({request_data.repo.type}), lang: {request_data.language}"
    )
    payload = WikiCacheData(
        project_id=request_data.project_id,
        language=request_data.language,
        comprehensive=request_data.comprehensive,
        wiki_structure=request_data.wiki_structure,
        generated_pages=request_data.generated_pages,
        repo=request_data.repo,
        provider=request_data.provider,
        model=request_data.model,
    ).model_dump()
    success = wiki_cache_service.save(payload)
    if success:
        return {"message": "Wiki cache saved successfully"}
    else:
        raise HTTPException(status_code=500, detail="Failed to save wiki cache")


@router.delete("/api/wiki_cache")
async def delete_wiki_cache(
    owner: str = Query(..., description="Repository owner"),
    repo: str = Query(..., description="Repository name"),
    repo_type: str = Query(..., description="Repository type (e.g., github, gitlab)"),
    language: str = Query(..., description="Language of the wiki content"),
    authorization_code: Optional[str] = Query(None, description="Authorization code"),
):
    """删除 Wiki 缓存"""
    supported_langs = configs.get("lang", {}).get("supported_languages", {})
    if language not in supported_langs:
        raise HTTPException(status_code=400, detail="Language is not supported")

    if WIKI_AUTH_MODE:
        logger.info("Checking authorization code")
        if not authorization_code or WIKI_AUTH_CODE != authorization_code:
            raise HTTPException(status_code=401, detail="Authorization code is invalid")

    logger.info(f"Deleting wiki cache for {owner}/{repo} ({repo_type}), lang: {language}")
    if wiki_cache_service.delete(owner, repo, repo_type, language):
        return {"message": f"Wiki cache for {owner}/{repo} ({language}) deleted successfully"}
    else:
        raise HTTPException(status_code=404, detail="Wiki cache not found")


# ============================================================
# 已处理项目列表
# ============================================================


@router.get("/api/processed_projects", response_model=List[ProcessedProjectEntry])
async def get_processed_projects():
    """
    列出所有已初始化项目（含已摄取但尚未生成 Wiki、正在处理中的项目）。

    数据源：projects LEFT JOIN wiki_structure(is_deleted=false)
      - 项目身份来自 projects
      - language / comprehensive 来自 wiki_structure；无变体时取默认值
    同一项目的多个语言/模式会返回多行。
    """
    default_language = configs.get("lang", {}).get("default", "en")
    project_entries: List[ProcessedProjectEntry] = []

    try:
        # 同步 DB 调用放入线程池，避免阻塞事件循环
        cached_projects = await asyncio.to_thread(
            wiki_cache_service.list_projects, default_language
        )

        for entry in cached_projects:
            try:
                project_entries.append(
                    ProcessedProjectEntry(
                        id=entry.get("id", ""),  # project_id
                        owner=entry.get("owner", "unknown"),
                        repo=entry.get("repo", ""),
                        name=entry.get("name", ""),
                        repo_type=entry.get("repo_type", "github"),
                        submittedAt=entry.get("submittedAt", 0),
                        language=entry.get("language", "en"),
                        comprehensive=entry.get("comprehensive", False),
                    )
                )
            except Exception as e:
                logger.error(f"Error processing project entry {entry.get('id')}: {e}")
                continue

        # 按时间排序（最新的在前）
        project_entries.sort(key=lambda p: p.submittedAt, reverse=True)
        logger.info(f"Found {len(project_entries)} processed project entries.")
        return project_entries

    except Exception as e:
        logger.error(f"Error listing processed projects: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list processed projects.")
