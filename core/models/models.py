"""
SQLAlchemy ORM 模型定义

对应 14 张数据库表，完整映射 RAG 系统的数据模型。
使用 SQLAlchemy 2.0 声明式映射风格。
"""

import uuid
from datetime import datetime
from typing import Optional, List

from sqlalchemy import (
    Column, String, Integer, Float, Boolean, Text, DateTime,
    ForeignKey, UniqueConstraint, Index, Enum as SAEnum,
    JSON, BigInteger, func
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import expression


# ============================================================
# 基础类
# ============================================================

class Base(DeclarativeBase):
    """SQLAlchemy 声明式基类"""
    pass


def gen_uuid():
    """生成 UUID v4"""
    return uuid.uuid4()


def utcnow():
    """当前 UTC 时间"""
    return datetime.utcnow()


# ============================================================
# 1. 嵌入模型注册表
# ============================================================

class EmbeddingModel(Base):
    """嵌入模型注册表"""
    __tablename__ = "embedding_models"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<EmbeddingModel(name='{self.name}', dim={self.dimensions})>"


# ============================================================
# 2. 项目/仓库表
# ============================================================

class Project(Base):
    """项目/仓库"""
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    repo_url: Mapped[Optional[str]] = mapped_column(Text, unique=True)
    owner: Mapped[Optional[str]] = mapped_column(String(255))
    repo_type: Mapped[str] = mapped_column(String(50), default="gitee")
    local_path: Mapped[Optional[str]] = mapped_column(Text)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    extra_metadata: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)

    # 关系
    documents: Mapped[List["RawDocument"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    wiki_pages: Mapped[List["WikiPage"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    wiki_structures: Mapped[List["WikiStructure"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    ingestion_jobs: Mapped[List["IngestionJob"]] = relationship(back_populates="project", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Project(name='{self.name}', url='{self.repo_url}')>"


# ============================================================
# 3. 原始文档表
# ============================================================

class RawDocument(Base):
    """原始文档"""
    __tablename__ = "raw_documents"
    __table_args__ = (
        UniqueConstraint("project_id", "file_path", name="unique_file_per_project"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_type: Mapped[Optional[str]] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[Optional[int]] = mapped_column(Integer)
    is_code: Mapped[bool] = mapped_column(Boolean, default=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    content_sha256: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # 关系
    project: Mapped["Project"] = relationship(back_populates="documents")
    chunks: Mapped[List["DocumentChunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<RawDocument(path='{self.file_path}', type='{self.file_type}')>"


# ============================================================
# 5. 文档分块表
# ============================================================

class DocumentChunk(Base):
    """文档分块"""
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="unique_chunk_per_doc"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("raw_documents.id", ondelete="CASCADE"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_size: Mapped[Optional[int]] = mapped_column(Integer)
    chunk_overlap: Mapped[Optional[int]] = mapped_column(Integer)
    split_by: Mapped[Optional[str]] = mapped_column(String(50))
    token_count: Mapped[Optional[int]] = mapped_column(Integer)
    start_offset: Mapped[Optional[int]] = mapped_column(Integer)
    end_offset: Mapped[Optional[int]] = mapped_column(Integer)
    extra_metadata: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # 关系
    document: Mapped["RawDocument"] = relationship(back_populates="chunks")
    embedding: Mapped[Optional["ChunkEmbeddingDim256"]] = relationship(back_populates="chunk", uselist=False, cascade="all, delete-orphan")

    def __repr__(self):
        return f"<DocumentChunk(doc_id={self.document_id}, idx={self.chunk_index})>"


# ============================================================
# 6. 向量嵌入表（256 维）
# ============================================================

class ChunkEmbeddingDim256(Base):
    """向量嵌入（256 维，text-embedding-v4）"""
    __tablename__ = "chunk_embeddings_dim256"
    __table_args__ = (
        UniqueConstraint("chunk_id", "model_id", name="unique_embedding_per_chunk_model"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    chunk_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("document_chunks.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    model_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("embedding_models.id"), nullable=False)

    # 向量字段 — 使用 Text 存储，实际查询时通过 raw SQL 使用 vector 类型
    embedding: Mapped[str] = mapped_column(Text, nullable=False, comment="Vector(256) as text representation")

    # 冗余字段
    content: Mapped[Optional[str]] = mapped_column(Text)
    file_path: Mapped[Optional[str]] = mapped_column(Text)
    chunk_index: Mapped[Optional[int]] = mapped_column(Integer)

    # 全文检索向量（自动生成，仅用于 ORM 映射，实际查询使用 raw SQL）
    fts_text: Mapped[Optional[str]] = mapped_column("fts_text", TSVECTOR, comment="Auto-generated tsvector for full-text search")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # 关系
    chunk: Mapped["DocumentChunk"] = relationship(back_populates="embedding")
    model: Mapped["EmbeddingModel"] = relationship()

    def __repr__(self):
        return f"<ChunkEmbedding(chunk_id={self.chunk_id}, model_id={self.model_id})>"


# ============================================================
# 8. 摄取任务表
# ============================================================

class IngestionJob(Base):
    """摄取任务"""
    __tablename__ = "ingestion_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)

    trigger_type: Mapped[str] = mapped_column(String(50), default="manual")
    status: Mapped[str] = mapped_column(String(20), default="pending")

    current_stage: Mapped[Optional[str]] = mapped_column(String(50))
    progress: Mapped[float] = mapped_column(Float, default=0.0)

    total_files: Mapped[int] = mapped_column(Integer, default=0)
    processed_files: Mapped[int] = mapped_column(Integer, default=0)

    error_message: Mapped[Optional[str]] = mapped_column(Text)
    error_detail: Mapped[Optional[dict]] = mapped_column(JSONB)

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # 关系
    project: Mapped["Project"] = relationship(back_populates="ingestion_jobs")
    pipeline_logs: Mapped[List["PipelineLog"]] = relationship(back_populates="job", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<IngestionJob(project_id={self.project_id}, status='{self.status}')>"


# ============================================================
# 9. 检索记录表
# ============================================================

class RetrievalLog(Base):
    """检索记录"""
    __tablename__ = "retrieval_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"))
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    query_embedding: Mapped[Optional[str]] = mapped_column(Text, comment="Vector(256) as text representation")

    top_k: Mapped[int] = mapped_column(Integer, default=5)
    retrieval_type: Mapped[str] = mapped_column(String(50), default="vector_only")
    hybrid_weight: Mapped[float] = mapped_column(Float, default=0.7)

    latency_ms: Mapped[Optional[int]] = mapped_column(Integer)

    # 溯源：检索用途与业务来源主键（wiki_pages.id / qa_logs.id）
    task: Mapped[str] = mapped_column(String(50), default="unknown")
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # 关系
    results: Mapped[List["RetrievalResult"]] = relationship(back_populates="retrieval_log", cascade="all, delete-orphan")
    qa_log: Mapped[Optional["QALog"]] = relationship(back_populates="retrieval_log", uselist=False)

    def __repr__(self):
        return f"<RetrievalLog(query='{self.query_text[:50]}', type='{self.retrieval_type}')>"


# ============================================================
# 10. 检索结果明细表
# ============================================================

class RetrievalResult(Base):
    """检索结果明细"""
    __tablename__ = "retrieval_results"
    __table_args__ = (
        UniqueConstraint("retrieval_id", "chunk_id", name="unique_result_per_retrieval"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    retrieval_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("retrieval_logs.id", ondelete="CASCADE"), nullable=False)
    chunk_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("document_chunks.id"))
    rank: Mapped[Optional[int]] = mapped_column(Integer)
    vector_score: Mapped[Optional[float]] = mapped_column(Float)
    keyword_score: Mapped[Optional[float]] = mapped_column(Float)
    final_score: Mapped[Optional[float]] = mapped_column(Float)
    extra_metadata: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)

    # 关系
    retrieval_log: Mapped["RetrievalLog"] = relationship(back_populates="results")

    def __repr__(self):
        return f"<RetrievalResult(retrieval_id={self.retrieval_id}, rank={self.rank})>"


# ============================================================
# 11. 问答记录表
# ============================================================

class QALog(Base):
    """问答记录"""
    __tablename__ = "qa_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    retrieval_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("retrieval_logs.id"))
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"))
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    response_text: Mapped[Optional[str]] = mapped_column(Text)
    model_name: Mapped[Optional[str]] = mapped_column(String(100))
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    total_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer)
    user_rating: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # 关系
    retrieval_log: Mapped[Optional["RetrievalLog"]] = relationship(back_populates="qa_log")

    def __repr__(self):
        return f"<QALog(query='{self.query_text[:50]}', model='{self.model_name}')>"


# ============================================================
# 12. 管道日志表
# ============================================================

class PipelineLog(Base):
    """管道日志"""
    __tablename__ = "pipeline_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"))
    job_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("ingestion_jobs.id"))

    step_name: Mapped[Optional[str]] = mapped_column(String(100))
    status: Mapped[Optional[str]] = mapped_column(String(20))
    input_count: Mapped[Optional[int]] = mapped_column(Integer)
    output_count: Mapped[Optional[int]] = mapped_column(Integer)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    parameters: Mapped[Optional[dict]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # 关系
    job: Mapped[Optional["IngestionJob"]] = relationship(back_populates="pipeline_logs")

    def __repr__(self):
        return f"<PipelineLog(step='{self.step_name}', status='{self.status}')>"


# ============================================================
# 13. Wiki 页面表
# ============================================================

class WikiPage(Base):
    """Wiki 页面"""
    __tablename__ = "wiki_pages"
    __table_args__ = (
        UniqueConstraint("project_id", "page_slug", name="unique_wiki_page"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    wiki_structure_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wiki_structure.id", ondelete="CASCADE")
    )
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)

    page_slug: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content_md: Mapped[Optional[str]] = mapped_column(Text)

    # 对齐前端 WikiPage 契约的页面属性
    file_paths: Mapped[list] = mapped_column(JSONB, default=list)
    importance: Mapped[str] = mapped_column(String(16), default="medium")
    related_pages: Mapped[list] = mapped_column(JSONB, default=list)

    # 目录树定位字段
    parent_id: Mapped[Optional[str]] = mapped_column(Text)
    is_section: Mapped[bool] = mapped_column(Boolean, default=False)
    children: Mapped[list] = mapped_column(JSONB, default=list)

    version: Mapped[int] = mapped_column(Integer, default=1)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # 关系
    project: Mapped["Project"] = relationship(back_populates="wiki_pages")

    def __repr__(self):
        return f"<WikiPage(slug='{self.page_slug}')>"


# ============================================================
# 14. Wiki 结构表
# ============================================================


class WikiStructure(Base):
    """Wiki 结构（存储 Wiki 结构 + 元数据，wiki_pages 的父级）"""
    __tablename__ = "wiki_structure"
    __table_args__ = (
        UniqueConstraint("project_id", "language", "is_comprehensive", name="unique_wiki_structure_per_project_lang"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)

    language: Mapped[str] = mapped_column(String(10), default="zh")
    is_comprehensive: Mapped[bool] = mapped_column(Boolean, default=True)

    # Wiki 结构（JSONB，包含 sections、page hierarchy 等）
    structure_json: Mapped[dict] = mapped_column(JSONB, default=dict)

    # LLM 配置（收敛到结构级，wiki_pages 不再冗余）
    provider: Mapped[Optional[str]] = mapped_column(String(50))
    model: Mapped[Optional[str]] = mapped_column(String(100))

    # 软删除
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # 关系
    project: Mapped["Project"] = relationship(back_populates="wiki_structures")

    def __repr__(self):
        return f"<WikiStructure(project={self.project_id}, lang='{self.language}')>"


# ============================================================
# 15. 对话历史表
# ============================================================

class Conversation(Base):
    """对话"""
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    provider: Mapped[Optional[str]] = mapped_column(String(50))
    model: Mapped[Optional[str]] = mapped_column(String(100))
    language: Mapped[str] = mapped_column(String(10), default="zh")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # 关系
    turns: Mapped[List["ConversationTurn"]] = relationship(back_populates="conversation", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Conversation(id={self.id}, lang='{self.language}')>"


class ConversationTurn(Base):
    """对话轮次"""
    __tablename__ = "conversation_turns"
    __table_args__ = (
        UniqueConstraint("conversation_id", "turn_index", name="unique_turn_per_conversation"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=gen_uuid)
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # 关系
    conversation: Mapped["Conversation"] = relationship(back_populates="turns")

    def __repr__(self):
        return f"<ConversationTurn(conv_id={self.conversation_id}, role='{self.role}')>"
