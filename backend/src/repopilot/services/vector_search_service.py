import hashlib
from datetime import UTC, datetime
from functools import lru_cache
from typing import Protocol

from openai import OpenAI
from qdrant_client import QdrantClient, models
from sqlalchemy import select
from sqlalchemy.orm import Session

from repopilot.core.config import settings
from repopilot.models.knowledge_chunk import KnowledgeChunk
from repopilot.models.repository_file import RepositoryFile
from repopilot.models.vector_index_state import VectorIndexState
from repopilot.schemas.retrieval import (
    SemanticSearchResponse,
    SemanticSearchResult,
    VectorIndexStatsResponse,
)


class EmptyKnowledgeBaseError(Exception):
    """项目尚未生成可供向量化的知识切片。"""


class VectorIndexNotReadyError(Exception):
    """项目的向量索引不存在，或者所用模型已经变化。"""


class EmbeddingConfigurationError(Exception):
    """Embedding API Key 尚未配置。"""


class EmbeddingProvider(Protocol):
    """隔离具体模型库，后续可替换为百炼 API 而不修改索引和检索逻辑。"""

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, query: str) -> list[float]: ...


class QwenApiEmbeddingProvider:
    def __init__(self) -> None:
        api_key = settings.qwen_api_key
        if not api_key:
            raise EmbeddingConfigurationError
        self.client = OpenAI(
            api_key=api_key,
            base_url=settings.embedding_api_base_url,
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), settings.embedding_batch_size):
            response = self.client.embeddings.create(
                model=settings.embedding_model_name,
                input=texts[start : start + settings.embedding_batch_size],
                dimensions=settings.embedding_dimensions,
                encoding_format="float",
            )
            vectors.extend(item.embedding for item in sorted(response.data, key=lambda x: x.index))
        return vectors

    def embed_query(self, query: str) -> list[float]:
        response = self.client.embeddings.create(
            model=settings.embedding_model_name,
            input=query,
            dimensions=settings.embedding_dimensions,
            encoding_format="float",
        )
        return response.data[0].embedding


@lru_cache
def get_embedding_provider() -> EmbeddingProvider:
    return QwenApiEmbeddingProvider()


@lru_cache
def get_qdrant_client() -> QdrantClient:
    if settings.vector_database_url:
        # 服务模式由 Qdrant 容器独占持久化目录，FastAPI 只通过 HTTP 访问。
        return QdrantClient(url=settings.vector_database_url)
    settings.vector_database_path.mkdir(parents=True, exist_ok=True)
    # 不配置 URL 时保留原有嵌入式模式，方便直接在 PyCharm 中开发。
    return QdrantClient(path=str(settings.vector_database_path))


def _project_filter(project_id: str) -> models.Filter:
    return models.Filter(
        must=[
            models.FieldCondition(
                key="project_id",
                match=models.MatchValue(value=project_id),
            )
        ]
    )


def _collection_name() -> str:
    # 模型或维度变化时使用新 collection，避免把不兼容的向量混在一起。
    identity = (
        f"{settings.embedding_api_base_url}|{settings.embedding_model_name}|"
        f"{settings.embedding_dimensions}"
    )
    suffix = hashlib.sha256(identity.encode()).hexdigest()[:10]
    return f"{settings.vector_collection_name}_{suffix}"


class VectorSearchService:
    @staticmethod
    def stats(session: Session, project_id: str) -> VectorIndexStatsResponse:
        state = session.get(VectorIndexState, project_id)
        ready = (
            state is not None
            and state.embedding_model == settings.embedding_model_name
            and state.vector_size == settings.embedding_dimensions
        )
        return VectorIndexStatsResponse(
            project_id=project_id,
            ready=ready,
            embedding_model=(state.embedding_model if state else settings.embedding_model_name),
            vector_size=state.vector_size if state else 0,
            indexed_chunks=state.indexed_chunks if ready and state else 0,
            indexed_at=state.indexed_at if ready and state else None,
        )

    @staticmethod
    def rebuild(session: Session, project_id: str) -> VectorIndexStatsResponse:
        rows = session.execute(
            select(KnowledgeChunk, RepositoryFile.path)
            .join(RepositoryFile, RepositoryFile.id == KnowledgeChunk.repository_file_id)
            .where(KnowledgeChunk.project_id == project_id)
            .order_by(RepositoryFile.path, KnowledgeChunk.chunk_index)
        ).all()
        if not rows:
            raise EmptyKnowledgeBaseError

        texts = [
            "\n".join(
                part
                for part in (
                    f"文件：{source_path}",
                    f"符号：{chunk.symbol_name}" if chunk.symbol_name else "",
                    chunk.content,
                )
                if part
            )
            for chunk, source_path in rows
        ]
        embedding_provider = get_embedding_provider()
        vectors = embedding_provider.embed_documents(texts)
        vector_size = len(vectors[0])
        client = get_qdrant_client()
        collection_name = _collection_name()
        if not client.collection_exists(collection_name):
            client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(
                    size=vector_size,
                    distance=models.Distance.COSINE,
                ),
            )
        else:
            # 先删除当前项目的旧向量，其他项目仍保留在同一个 collection 中。
            client.delete(
                collection_name=collection_name,
                points_selector=models.FilterSelector(filter=_project_filter(project_id)),
                wait=True,
            )

        points = [
            models.PointStruct(
                id=chunk.id,
                vector=vector,
                payload={
                    "project_id": project_id,
                    "chunk_id": chunk.id,
                    "source_path": source_path,
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                    "symbol_name": chunk.symbol_name,
                    "strategy": chunk.strategy,
                    "content": chunk.content,
                },
            )
            for (chunk, source_path), vector in zip(rows, vectors, strict=True)
        ]
        client.upsert(
            collection_name=collection_name,
            points=points,
            wait=True,
        )

        # Qdrant 写入成功后才更新 SQLite 状态，避免把不完整索引标记成可检索。
        session.merge(
            VectorIndexState(
                project_id=project_id,
                embedding_model=settings.embedding_model_name,
                vector_size=vector_size,
                indexed_chunks=len(points),
                indexed_at=datetime.now(UTC),
            )
        )
        session.commit()
        return VectorSearchService.stats(session, project_id)

    @staticmethod
    def search(
        session: Session,
        project_id: str,
        query: str,
        limit: int,
        score_threshold: float | None,
    ) -> SemanticSearchResponse:
        state = session.get(VectorIndexState, project_id)
        if (
            state is None
            or state.embedding_model != settings.embedding_model_name
            or state.vector_size != settings.embedding_dimensions
        ):
            raise VectorIndexNotReadyError

        query_vector = get_embedding_provider().embed_query(query)
        points = get_qdrant_client().query_points(
            collection_name=_collection_name(),
            query=query_vector,
            query_filter=_project_filter(project_id),
            limit=limit,
            score_threshold=score_threshold,
            with_payload=True,
        ).points
        return SemanticSearchResponse(
            project_id=project_id,
            query=query,
            results=[
                SemanticSearchResult(
                    chunk_id=point.payload["chunk_id"],
                    score=point.score,
                    source_path=point.payload["source_path"],
                    start_line=point.payload["start_line"],
                    end_line=point.payload["end_line"],
                    symbol_name=point.payload.get("symbol_name"),
                    strategy=point.payload["strategy"],
                    content=point.payload["content"],
                )
                for point in points
                if point.payload is not None
            ],
        )


vector_search_service = VectorSearchService()
