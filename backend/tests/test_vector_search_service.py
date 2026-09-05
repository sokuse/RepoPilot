from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from repopilot.db.base import Base
from repopilot.models.knowledge_chunk import KnowledgeChunk
from repopilot.models.project import Project
from repopilot.models.repository_file import RepositoryFile
from repopilot.services import vector_search_service as vector_search_module
from repopilot.services.vector_search_service import VectorSearchService


class FakeEmbeddingProvider:
    def embed_documents(self, texts):
        return [[1.0, float(index), 0.5] for index, _ in enumerate(texts)]

    def embed_query(self, _query):
        return [1.0, 0.0, 0.5]


class FakeQdrantClient:
    def __init__(self) -> None:
        self.exists = False
        self.points = []

    def collection_exists(self, _collection_name: str) -> bool:
        return self.exists

    def create_collection(self, **_kwargs) -> None:
        self.exists = True

    def delete(self, **_kwargs) -> None:
        self.points = []

    def upsert(self, *, points, **_kwargs) -> None:
        self.points = points

    def query_points(self, **_kwargs):
        point = self.points[0]
        return SimpleNamespace(
            points=[SimpleNamespace(payload=point.payload, score=0.91)]
        )


def test_qdrant_client_uses_server_url_when_configured(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def create_client(*, url: str):
        captured["url"] = url
        return object()

    vector_search_module.get_qdrant_client.cache_clear()
    monkeypatch.setattr(
        vector_search_module.settings,
        "vector_database_url",
        "http://qdrant:6333",
    )
    monkeypatch.setattr(vector_search_module, "QdrantClient", create_client)

    try:
        vector_search_module.get_qdrant_client()
    finally:
        # 避免缓存的测试对象影响后续用例。
        vector_search_module.get_qdrant_client.cache_clear()

    assert captured["url"] == "http://qdrant:6333"


def test_build_and_search_vector_index(monkeypatch) -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    fake_client = FakeQdrantClient()
    monkeypatch.setattr(
        "repopilot.services.vector_search_service.settings.embedding_dimensions",
        3,
    )
    monkeypatch.setattr(
        "repopilot.services.vector_search_service.get_embedding_provider",
        lambda: FakeEmbeddingProvider(),
    )
    monkeypatch.setattr(
        "repopilot.services.vector_search_service.get_qdrant_client",
        lambda: fake_client,
    )

    with Session(engine) as session:
        project = Project(
            name="Demo",
            repository_url="https://github.com/example/demo",
            default_branch="main",
            status="ready",
        )
        session.add(project)
        session.flush()
        repository_file = RepositoryFile(
            project_id=project.id,
            path="src/main.py",
            extension=".py",
            language="Python",
            size_bytes=20,
            content_sha256="file-hash",
        )
        session.add(repository_file)
        session.flush()
        session.add(
            KnowledgeChunk(
                project_id=project.id,
                repository_file_id=repository_file.id,
                chunk_index=0,
                strategy="python_ast",
                content="def create_app(): pass",
                content_sha256="chunk-hash",
                char_count=22,
                start_line=10,
                end_line=10,
                symbol_name="create_app",
                extra_metadata={},
            )
        )
        session.commit()

        stats = VectorSearchService.rebuild(session, project.id)
        response = VectorSearchService.search(
            session, project.id, "在哪里创建应用", limit=5, score_threshold=None
        )

    assert stats.ready is True
    assert stats.vector_size == 3
    assert stats.indexed_chunks == 1
    assert response.results[0].source_path == "src/main.py"
    assert response.results[0].symbol_name == "create_app"
    assert response.results[0].score == 0.91
