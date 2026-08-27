"""
OpenWiki-Study API 端点

使用 PostgreSQL + pgvector 后端替代原始 LocalDB + .pkl 存储。
保持与原始 deepwiki-open 前端兼容的 API 接口。
"""

import os
import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from api.config import configs, WIKI_AUTH_MODE, WIKI_AUTH_CODE
from infra.cache.base import WikiCacheStorage
from infra.cache.filesystem import FileSystemWikiCacheStorage
from infra.cache.key import get_cache_key
from infra.db.repository import ProjectRepository

logger = logging.getLogger(__name__)


# ============================================================
# API 路由定义（app 由 api/main.py 创建并挂载）
# ============================================================

api_router = APIRouter()

# Wiki 数据存储实例（当前默认文件系统实现，行为向后兼容；
# 切换为 PG+Redis 生产形态只需改为 DbRedisWikiCacheStorage()）
wiki_storage: WikiCacheStorage = FileSystemWikiCacheStorage()


# ============================================================
# Pydantic 模型
# ============================================================


class WikiPage(BaseModel):
    """Wiki 页面模型"""
    id: str
    title: str
    content: str
    filePaths: List[str]
    importance: str  # high, medium, low
    relatedPages: List[str] = []  # 相关页面 ID 列表


class ProcessedProjectEntry(BaseModel):
    """已处理项目条目"""
    id: str
    owner: str
    repo: str
    name: str
    repo_type: str
    submittedAt: int
    language: str
    comprehensive: bool


class RepoInfo(BaseModel):
    """仓库信息"""
    owner: str
    repo: str
    type: str
    token: Optional[str] = None
    localPath: Optional[str] = None
    repoUrl: Optional[str] = None


class WikiSection(BaseModel):
    """Wiki 章节"""
    id: str
    title: str
    pages: List[str]
    subsections: Optional[List[str]] = None


class WikiStructureModel(BaseModel):
    """Wiki 结构模型"""
    id: str
    title: str
    description: str
    pages: List[WikiPage]
    sections: Optional[List[WikiSection]] = None
    rootSections: Optional[List[str]] = None


class WikiCacheData(BaseModel):
    """Wiki 缓存数据"""
    wiki_structure: WikiStructureModel
    generated_pages: Dict[str, WikiPage]
    repo_url: Optional[str] = None
    repo: Optional[RepoInfo] = None
    provider: Optional[str] = None
    model: Optional[str] = None


class WikiCacheRequest(BaseModel):
    """Wiki 缓存请求"""
    repo: RepoInfo
    language: str
    comprehensive: bool
    wiki_structure: WikiStructureModel
    generated_pages: Dict[str, WikiPage]
    provider: str
    model: str


class WikiExportRequest(BaseModel):
    """Wiki 导出请求"""
    repo_url: str = Field(..., description="Repository URL")
    pages: List[WikiPage] = Field(..., description="Wiki pages to export")
    format: Literal["markdown", "json"] = Field(..., description="Export format")


class Model(BaseModel):
    """LLM 模型"""
    id: str
    name: str


class Provider(BaseModel):
    """LLM 提供者"""
    id: str
    name: str
    models: List[Model]
    supportsCustomModel: Optional[bool] = False


class ModelConfig(BaseModel):
    """模型配置"""
    providers: List[Provider]
    defaultProvider: str


class AuthorizationConfig(BaseModel):
    """授权配置"""
    code: str


# ============================================================
# API 端点
# ============================================================


@api_router.get("/lang/config")
async def get_lang_config():
    """获取语言配置"""
    return configs.get("lang", {
        "supported_languages": {"en": "English"},
        "default": "zh",
    })


@api_router.get("/auth/status")
async def get_auth_status():
    """检查是否需要认证"""
    return {"auth_required": WIKI_AUTH_MODE}


@api_router.post("/auth/validate")
async def validate_auth_code(request: AuthorizationConfig):
    """验证授权码"""
    return {"success": WIKI_AUTH_CODE == request.code}


@api_router.get("/models/config", response_model=ModelConfig)
async def get_model_config():
    """
    获取可用的模型提供者和模型列表

    从 generator.json 配置中读取提供者和模型信息。
    """
    try:
        logger.info("Fetching model configurations")

        providers = []
        default_provider = configs.get("default_provider", "dashscope")

        for provider_id, provider_config in configs.get("providers", {}).items():
            models = []
            for model_id in provider_config.get("models", {}).keys():
                models.append(Model(id=model_id, name=model_id))

            providers.append(
                Provider(
                    id=provider_id,
                    name=provider_id.capitalize(),
                    supportsCustomModel=provider_config.get("supportsCustomModel", False),
                    models=models,
                )
            )

        return ModelConfig(providers=providers, defaultProvider=default_provider)

    except Exception as e:
        logger.error(f"Error creating model configuration: {str(e)}")
        return ModelConfig(
            providers=[
                Provider(
                    id="dashscope",
                    name="DashScope",
                    supportsCustomModel=True,
                    models=[Model(id="qwen-plus", name="Qwen Plus")],
                )
            ],
            defaultProvider="dashscope",
        )


@api_router.post("/export/wiki")
async def export_wiki(request: WikiExportRequest):
    """
    导出 Wiki 内容为 Markdown 或 JSON

    Args:
        request: 导出请求

    Returns:
        可下载的文件
    """
    try:
        logger.info(f"Exporting wiki for {request.repo_url} in {request.format} format")

        repo_parts = request.repo_url.rstrip("/").split("/")
        repo_name = repo_parts[-1] if repo_parts else "wiki"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if request.format == "markdown":
            content = generate_markdown_export(request.repo_url, request.pages)
            filename = f"{repo_name}_wiki_{timestamp}.md"
            media_type = "text/markdown"
        else:
            content = generate_json_export(request.repo_url, request.pages)
            filename = f"{repo_name}_wiki_{timestamp}.json"
            media_type = "application/json"

        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    except Exception as e:
        error_msg = f"Error exporting wiki: {str(e)}"
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)


@api_router.get("/local_repo/structure")
async def get_local_repo_structure(path: str = Query(None, description="Path to local repository")):
    """返回本地仓库的文件树和 README 内容"""
    if not path:
        return JSONResponse(
            status_code=400,
            content={"error": "No path provided. Please provide a 'path' query parameter."},
        )

    if not os.path.isdir(path):
        return JSONResponse(
            status_code=404,
            content={"error": f"Directory not found: {path}"},
        )

    try:
        logger.info(f"Processing local repository at: {path}")
        file_tree_lines = []
        readme_content = ""

        for root, dirs, files in os.walk(path):
            dirs[:] = [
                d for d in dirs
                if not d.startswith(".")
                and d != "__pycache__"
                and d != "node_modules"
                and d != ".venv"
            ]
            for file in files:
                if file.startswith(".") or file == "__init__.py" or file == ".DS_Store":
                    continue
                rel_dir = os.path.relpath(root, path)
                rel_file = os.path.join(rel_dir, file) if rel_dir != "." else file
                file_tree_lines.append(rel_file)
                if file.lower() == "readme.md" and not readme_content:
                    try:
                        with open(os.path.join(root, file), "r", encoding="utf-8") as f:
                            readme_content = f.read()
                    except Exception as e:
                        logger.warning(f"Could not read README.md: {str(e)}")
                        readme_content = ""

        file_tree_str = "\n".join(sorted(file_tree_lines))
        return {"file_tree": file_tree_str, "readme": readme_content}

    except Exception as e:
        logger.error(f"Error processing local repository: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Error processing local repository: {str(e)}"},
        )


# ============================================================
# Wiki 导出辅助函数
# ============================================================


def generate_markdown_export(repo_url: str, pages: List[WikiPage]) -> str:
    """生成 Markdown 导出"""
    markdown = f"# Wiki Documentation for {repo_url}\n\n"
    markdown += f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    markdown += "## Table of Contents\n\n"
    for page in pages:
        markdown += f"- [{page.title}](#{page.id})\n"
    markdown += "\n"

    for page in pages:
        markdown += f"<a id='{page.id}'></a>\n\n"
        markdown += f"## {page.title}\n\n"

        if page.relatedPages and len(page.relatedPages) > 0:
            markdown += "### Related Pages\n\n"
            related_titles = []
            for related_id in page.relatedPages:
                related_page = next((p for p in pages if p.id == related_id), None)
                if related_page:
                    related_titles.append(f"[{related_page.title}](#{related_id})")
            if related_titles:
                markdown += "Related topics: " + ", ".join(related_titles) + "\n\n"

        markdown += f"{page.content}\n\n"
        markdown += "---\n\n"

    return markdown


def generate_json_export(repo_url: str, pages: List[WikiPage]) -> str:
    """生成 JSON 导出"""
    export_data = {
        "metadata": {
            "repository": repo_url,
            "generated_at": datetime.now().isoformat(),
            "page_count": len(pages),
        },
        "pages": [page.model_dump() for page in pages],
    }
    return json.dumps(export_data, indent=2)


# ============================================================
# 导入聊天和 WebSocket 端点
# ============================================================
from api.wiki_generation import wiki_router
from api.simple_chat import router as chat_router
from api.websocket_wiki import handle_websocket_chat

# 注册 sse 流式 wiki 生成路由
api_router.include_router(wiki_router)

# 注册聊天路由 sse 流式
api_router.include_router(chat_router)

# WebSocket 端点由 api/main.py 注册（app 唯一入口）
# 此处保留 handle_websocket_chat 导入供 main.py 使用


# ============================================================
# Wiki 缓存 API 端点（存储实现收敛到 infra.cache，经 wiki_storage 接口调用）
# ============================================================


@api_router.get("/api/wiki_cache", response_model=Optional[WikiCacheData])
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


@api_router.post("/api/wiki_cache")
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


@api_router.delete("/api/wiki_cache")
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
# 健康检查和根端点
# ============================================================


@api_router.get("/health")
async def health_check():
    """健康检查端点"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "openwiki-api",
        "version": "2.0.0",
    }


@api_router.get("/")
async def root():
    """根端点 — 列出所有可用端点"""
    endpoints = {}
    for route in api_router.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if path and methods:
            if path in ["/openapi.json", "/docs", "/redoc", "/favicon.ico"]:
                continue
            path_parts = path.strip("/").split("/")
            group = path_parts[0].capitalize() if path_parts[0] else "Root"
            method_list = list(methods - {"HEAD", "OPTIONS"})
            for method in method_list:
                endpoints.setdefault(group, []).append(f"{method} {path}")

    for group in endpoints:
        endpoints[group].sort()

    return {
        "message": "Welcome to OpenWiki API (RAG Optimized)",
        "version": "2.0.0",
        "endpoints": endpoints,
    }


# ============================================================
# 已处理项目列表
# ============================================================


@api_router.get("/api/processed_projects", response_model=List[ProcessedProjectEntry])
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
