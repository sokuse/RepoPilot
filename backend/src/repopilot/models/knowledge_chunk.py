from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from repopilot.db.base import Base


class KnowledgeChunk(Base):
    """供 RAG 检索使用的知识切片，并保留回到源代码所需的追溯信息。"""

    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint(
            "repository_file_id",
            "chunk_index",
            name="uq_knowledge_chunks_file_index",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    repository_file_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("repository_files.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    strategy: Mapped[str] = mapped_column(String(40), index=True)
    content: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    char_count: Mapped[int] = mapped_column(Integer)
    start_line: Mapped[int] = mapped_column(Integer)
    end_line: Mapped[int] = mapped_column(Integer)
    symbol_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    extra_metadata: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
