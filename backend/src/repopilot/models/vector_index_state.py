from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from repopilot.db.base import Base


class VectorIndexState(Base):
    """记录项目当前有效的向量索引版本；向量正文存放在 Qdrant。"""

    __tablename__ = "vector_index_states"

    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    embedding_model: Mapped[str] = mapped_column(String(200))
    vector_size: Mapped[int] = mapped_column(Integer)
    indexed_chunks: Mapped[int] = mapped_column(Integer)
    indexed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
