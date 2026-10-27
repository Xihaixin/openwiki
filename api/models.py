"""
api.models — API 契约模型（Pydantic DTO）
===========================================

API 层与前端通信的请求/响应模型。

分层说明：
  - core/models/schemas — 跨层共享的 Wiki 契约（页面、结构、缓存 payload）
  - api/models          — 复用 schemas，并补充 HTTP 专属的请求/响应模型
  - 各 router           — 模块专属的请求模型保留在各自模块内（如 wiki.py、chat.py）

注意：这些字段名（如 filePaths、repo_url）与前端契约严格绑定，改动需同步前端。
"""

from typing import Dict, List, Literal

from pydantic import BaseModel, Field

from core.models.schemas import (
    RepoInfo,
    WikiCacheData,
    WikiPage,
    WikiSection,
    WikiStructureModel,
)

__all__ = [
    "RepoInfo",
    "WikiCacheData",
    "WikiPage",
    "WikiSection",
    "WikiStructureModel",
    "ProcessedProjectEntry",
    "WikiCacheRequest",
    "WikiExportRequest",
]


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


class WikiCacheRequest(BaseModel):
    """Wiki 缓存请求"""
    project_id: str
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
