"""
api.models — API 契约模型（Pydantic DTO）
===========================================

API 层与前端通信的请求/响应模型。

分层说明：
  - core/models   — 领域模型（dataclass），承载业务数据
  - api/models    — API 契约模型（Pydantic），承载 HTTP 请求/响应结构
  - 各 router     — 模块专属的请求模型保留在各自模块内（如 wiki.py、chat.py）

注意：这些字段名（如 filePaths、repo_url）与前端契约严格绑定，改动需同步前端。
"""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


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
