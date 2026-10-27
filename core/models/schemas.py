"""
core.models.schemas — Wiki 契约模型（Pydantic DTO）
====================================================

跨层共享的 Wiki 数据结构契约，同时被 API 层与缓存/服务层使用：

  - api.models          — 复用本模块，补充 HTTP 专属的请求/响应模型
  - core.services       — 用本模块校验缓存 payload（避免 infra 依赖 api）
  - infra.cache         — 只处理 JSON dict，不直接依赖本模块

注意：
  - 字段名（filePaths / relatedPages / repo_url 等）与前端契约严格绑定，
    改动需同步 `src/app/[owner]/[repo]/page.tsx`。
  - 与 `core.models.__init__` 中的 dataclass 领域模型同名但用途不同：
    本模块是**传输/校验契约**，dataclass 是**业务流程内的领域对象**。
"""

from typing import Dict, List, Literal, Optional

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
    """Wiki 缓存数据（Redis 整包 payload 的契约）"""
    project_id: str
    repo: Optional[RepoInfo] = None
    language: str
    comprehensive: bool
    wiki_structure: WikiStructureModel
    generated_pages: Dict[str, WikiPage]
    repo_url: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
