from sqlalchemy import BigInteger, Text, Integer, DateTime, Index, ForeignKey, UniqueConstraint, CheckConstraint, Boolean, text
from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped, relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import TSVECTOR
from datetime import datetime
from pgvector.sqlalchemy import VECTOR, SPARSEVEC


class Base(DeclarativeBase):
    pass


KB_INGEST_STATUS_INGESTING = "ingesting"
KB_INGEST_STATUS_SUCCEEDED = "succeeded"
KB_INGEST_STATUS_FAILED = "failed"
KB_INGEST_STATUS_VALUES = (
    KB_INGEST_STATUS_INGESTING,
    KB_INGEST_STATUS_SUCCEEDED,
    KB_INGEST_STATUS_FAILED,
)


class TimestampMixin:
    create_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="创建时间",
    )
    update_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间",
    )


class SoftDeleteMixin:
    is_deleted: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
        index=True,
        comment="是否删除：0-未删除，1-已删除",
    )


class KnowledgeBase(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "knowledge_base"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    file_name: Mapped[str] = mapped_column(Text, nullable=True)  # 记录原始文件名
    project_id: Mapped[int] = mapped_column(BigInteger, nullable=True, index=True)  # 可选的项目ID，便于多项目管理
    qa_items: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
        index=True,
        comment="是否为项目级QA专用KB",
    )
    ingest_status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=KB_INGEST_STATUS_INGESTING,
        index=True,
        comment="入库状态：ingesting/succeeded/failed",
    )
    success_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
        comment="最近一次入库任务成功写入条数",
    )
    failed_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
        comment="最近一次入库任务失败条数",
    )
    items: Mapped[list["Item"]] = relationship(back_populates="kb")

    __table_args__ = (
        Index(
            "uq_knowledge_base_project_qa_items",
            "project_id",
            unique=True,
            postgresql_where=text("qa_items = true AND is_deleted = 0"),
        ),
        CheckConstraint(
            "ingest_status IN ('ingesting', 'succeeded', 'failed')",
            name="ck_knowledge_base_ingest_status",
        ),
    )


class Item(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "item"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInteger, nullable=True, index=True)  # 可选的项目ID，便于多项目管理  

    kb_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_base.id"),
        index=True,
        nullable=False,
    )
    kb: Mapped["KnowledgeBase"] = relationship(back_populates="items")

    # ✅ 新增：chunk 在文件内的顺序（0,1,2,...）
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)

    origin_text: Mapped[str] = mapped_column(Text)
    question: Mapped[str | None] = mapped_column(Text, nullable=True, comment="QA问题")
    answer: Mapped[str | None] = mapped_column(Text, nullable=True, comment="QA答案")

    embedding = mapped_column(VECTOR(1024))
    fts: Mapped[object] = mapped_column(TSVECTOR, nullable=True)

    __table_args__ = (
        # ✅ 幂等/补插关键：同一文件同一序号只能有一条
        UniqueConstraint("kb_id", "chunk_index", name="uq_item_kb_chunk_index"),

        # ✅ 常用查询：按文件 + 顺序取 chunk
        Index("idx_item_kb_chunk_index", "kb_id", "chunk_index"),

        # ✅ BM25 倒排索引
        Index("idx_item_fts_gin", "fts", postgresql_using="gin"),

        # ✅ 向量索引（embedding）
        Index(
            "idx_item_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
