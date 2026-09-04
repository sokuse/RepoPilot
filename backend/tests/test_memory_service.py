from qdrant_client import QdrantClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from repopilot.db.base import Base
from repopilot.models.conversation import MemoryChunk
from repopilot.models.project import Project
from repopilot.services.memory_service import MemoryService


class FakeEmbeddingProvider:
    @staticmethod
    def _vector(text: str) -> list[float]:
        lowered = text.lower()
        return [
            float("fastapi" in lowered),
            float("proxy" in lowered or "代理" in text),
            float("database" in lowered or "数据库" in text),
            0.1,
        ]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, query: str) -> list[float]:
        return self._vector(query)


def test_memory_is_chunked_indexed_searched_and_traceable(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    qdrant = QdrantClient(":memory:")
    monkeypatch.setattr(
        "repopilot.services.memory_service.get_embedding_provider",
        lambda: FakeEmbeddingProvider(),
    )
    monkeypatch.setattr(
        "repopilot.services.memory_service.get_qdrant_client",
        lambda: qdrant,
    )

    with session_factory() as session:
        project = Project(
            name="RepoPilot",
            repository_url="https://example.com/repopilot",
            status="ready",
        )
        session.add(project)
        session.commit()

        chunks = MemoryService.remember(
            session,
            project.id,
            "diagnosis",
            "diagnosis-1",
            "代理配置导致 GitHub 连接失败，修复 proxy 后恢复。",
        )
        results = MemoryService.search(project.id, "proxy 代理问题", 3)
        stats = MemoryService.stats(session, project.id)

        assert len(chunks) == 1
        assert results[0].source_type == "diagnosis"
        assert results[0].source_id == "diagnosis-1"
        assert "代理配置" in results[0].content
        assert stats.indexed_memories == 1
        assert session.get(MemoryChunk, str(results[0].memory_id)) is not None

    qdrant.close()
