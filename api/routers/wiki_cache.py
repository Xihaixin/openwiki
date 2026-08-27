"""
api.routers.wiki_cache — Wiki 缓存端点
======================================

缓存结果（Wiki 页面与结构）的查询、保存、删除，以及已处理项目列表。

存储实现收敛到 infra.cache，经 WikiCacheStorage 接口调用：
  - 当前默认文件系统实现（行为向后兼容）
  - 切换为 PG+Redis 生产形态只需替换 wiki_storage 实例
"""

import asyncio
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api.config import WIKI_AUTH_CODE, WIKI_AUTH_MODE, configs
from api.models import (
    ProcessedProjectEntry,
    WikiCacheData,
    WikiCacheRequest,
)
from infra.cache.base import WikiCacheStorage
from infra.cache.filesystem import FileSystemWikiCacheStorage
from infra.db.repository import ProjectRepository

logger = logging.getLogger(__name__)

router = APIRouter()

# Wiki 数据存储实例（当前默认文件系统实现，行为向后兼容；
# 切换为 PG+Redis 生产形态只需改为 DbRedisWikiCacheStorage()）
wiki_storage: WikiCacheStorage = FileSystemWikiCacheStorage()


# ============================================================
# Wiki 缓存 CRUD
# ============================================================


@router.get("/api/wiki_cache", response_model=Optional[WikiCacheData])
async def get_cached_wiki(
    owner: str = Query(..., description="Repository owner"),
    repo: str = Query(..., description="Repository name"),
    repo_type: str = Query(..., description="Repository type (e.g., github, gitlab)"),
    language: str = Query(..., description="Language of the wiki content"),
    comprehensive: bool = Query(...,description="use comprehensive or not"),
):
    """获取缓存的 Wiki 数据"""
    supported_langs = configs.get("lang", {}).get("supported_languages", {})
    if language not in supported_langs:
        language = configs.get("lang", {}).get("default", "en")

    logger.info(f"Retrieving wiki cache for {owner}/{repo} ({repo_type}), lang: {language}")
    cached_data = wiki_storage.read(owner, repo, repo_type, language, comprehensive)
    if cached_data:
        return WikiCacheData(**cached_data)
    else:
        logger.info(f"Wiki cache not found for {owner}/{repo} ({repo_type}), lang: {language}")
        return None


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
        wiki_structure=request_data.wiki_structure,
        generated_pages=request_data.generated_pages,
        repo=request_data.repo,
        provider=request_data.provider,
        model=request_data.model,
    ).model_dump()
    success = wiki_storage.save(payload, language=request_data.language, comprehensive=request_data.comprehensive)
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
    if wiki_storage.delete(owner, repo, repo_type, language):
        return {"message": f"Wiki cache for {owner}/{repo} ({language}) deleted successfully"}
    else:
        raise HTTPException(status_code=404, detail="Wiki cache not found")


# ============================================================
# 已处理项目列表
# ============================================================


@router.get("/api/processed_projects", response_model=List[ProcessedProjectEntry])
async def get_processed_projects():
    """
    列出所有已处理的项目

    从 PostgreSQL 数据库中获取项目列表
    """
    project_entries: List[ProcessedProjectEntry] = []

    try:
        # 1. 从存储层扫描已处理项目（文件系统实现扫描缓存目录；DB 实现扫描 wiki_caches 表）
        cached_projects = await asyncio.to_thread(wiki_storage.list_projects)
        for entry in cached_projects:
            try:
                project_entries.append(
                    ProcessedProjectEntry(
                        id=entry.get("id", ""),
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

        # 2. 从 PostgreSQL 数据库获取项目列表作为补充
        try:
            db_projects = ProjectRepository.list_all()
            for proj in db_projects:
                # 检查是否已存在（避免重复）
                existing_ids = {p.id for p in project_entries}
                proj_id = str(proj.get("id", ""))
                if proj_id not in existing_ids:
                    created_at = proj.get("created_at")
                    if isinstance(created_at, datetime):
                        timestamp = int(created_at.timestamp() * 1000)
                    else:
                        timestamp = 0

                    project_entries.append(
                        ProcessedProjectEntry(
                            id=proj_id,
                            owner=proj.get("owner") or "unknown",
                            repo=proj.get("name") or "unknown",
                            name=f"{proj.get('owner') or 'unknown'}/{proj.get('name') or 'unknown'}",
                            repo_type=proj.get("repo_type") or "github",
                            submittedAt=timestamp,
                            language="en",
                        )
                    )
        except Exception as e:
            logger.warning(f"Could not fetch projects from database: {e}")

        # 按时间排序（最新的在前）
        project_entries.sort(key=lambda p: p.submittedAt, reverse=True)
        logger.info(f"Found {len(project_entries)} processed project entries.")
        return project_entries

    except Exception as e:
        logger.error(f"Error listing processed projects: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list processed projects.")
