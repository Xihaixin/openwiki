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
    """Wiki 页面模型

    与前端 page.tsx 的 WikiPage 接口严格对齐：
      id / title / content / filePaths / importance / relatedPages
      parentId / isSection / children —— 用于在目录树中定位页面（所属 section、父节点、子节点）
    """
    id: str
    title: str
    content: str = ""
    filePaths: List[str] = Field(default_factory=list)
    importance: Literal["high", "medium", "low"] = "medium"
    relatedPages: List[str] = Field(default_factory=list)  # 相关页面 ID 列表
    parentId: Optional[str] = None
    isSection: bool = False
    children: List[str] = Field(default_factory=list)


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
    project_id:str
    repo: Optional[RepoInfo] = None
    language: str
    comprehensive: bool
    wiki_structure: WikiStructureModel
    generated_pages: Dict[str, WikiPage]
    repo_url: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None


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
