"""
api.routers — API 路由模块聚合
===============================

每个子模块对应一个独立业务模块的端点集合，避免端点混杂：

  - system.py      — 系统配置（lang / auth / models）
  - wiki_cache.py  — Wiki 缓存（查询 / 保存 / 删除 + 已处理项目列表）
  - export.py      — Wiki 导出（markdown / json）
  - local_repo.py  — 本地仓库结构
  - wiki.py        — Wiki 生成（SSE 流式）
  - chat.py        — 聊天（SSE 流式）
  - meta.py        — 健康检查

根端点（/）在此聚合层定义，遍历完整路由表列出所有可用端点。
"""

from fastapi import APIRouter

from api.routers.chat import router as chat_router
from api.routers.export import router as export_router
from api.routers.local_repo import router as local_repo_router
from api.routers.meta import router as meta_router
from api.routers.system import router as system_router
from api.routers.wiki import wiki_router
from api.routers.wiki_cache import router as wiki_cache_router

api_router = APIRouter()

api_router.include_router(system_router)
api_router.include_router(wiki_cache_router)
api_router.include_router(export_router)
api_router.include_router(local_repo_router)
api_router.include_router(wiki_router)
api_router.include_router(chat_router)
api_router.include_router(meta_router)


@api_router.get("/")
async def root():
    """根端点 — 列出所有可用端点"""
    from datetime import datetime

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
