import hashlib
from uuid import uuid4

from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client import models
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from repopilot.core.config import settings
from repopilot.models.conversation import MemoryChunk
from repopilot.schemas.conversation import MemorySearchResult, MemoryStats
from repopilot.services.vector_search_service import get_embedding_provider, get_qdrant_client


def _memory_collection_name() -> str:
    identity = (
        f"{settings.embedding_api_base_url}|{settings.embedding_model_name}|"
        f"{settings.embedding_dimensions}"
    )
    suffix = hashlib.sha256(identity.encode()).hexdigest()[:10]
    return f"{settings.memory_vector_collection_name}_{suffix}"


def _memory_filter(
    project_id: str,
    source_id: str | None = None,
    conversation_id: str | None = None,
) -> models.Filter:
    conditions = [
        models.FieldCondition(key="project_id", match=models.MatchValue(value=project_id))
    ]
    if source_id:
        conditions.append(
            models.FieldCondition(key="source_id", match=models.MatchValue(value=source_id))
        )
    if conversation_id:
        conditions.append(
            models.FieldCondition(
                key="conversation_id",
                match=models.MatchValue(value=conversation_id),
            )
        )
    return models.Filter(must=conditions)


class MemoryService:
    @staticmethod
    def remember(
        session: Session,
        project_id: str,
        source_type: str,
        source_id: str,
        content: str,
        conversation_id: str | None = None,
    ) -> list[MemoryChunk]:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.memory_chunk_size_chars,
            chunk_overlap=settings.memory_chunk_overlap_chars,
            length_function=len,
        )
        texts = [text for text in splitter.split_text(content) if text.strip()]
        if not texts:
            return []
        vectors = get_embedding_provider().embed_documents(texts)
        chunks = [
            MemoryChunk(
                id=str(uuid4()),
                project_id=project_id,
                conversation_id=conversation_id,
                source_type=source_type,
                source_id=source_id,
                chunk_index=index,
                content=text,
            )
            for index, text in enumerate(texts)
        ]
        client = get_qdrant_client()
        collection_name = _memory_collection_name()
        if not client.collection_exists(collection_name):
            client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(
                    size=len(vectors[0]),
                    distance=models.Distance.COSINE,
                ),
            )
        else:
            client.delete(
                collection_name=collection_name,
                points_selector=models.FilterSelector(filter=_memory_filter(project_id, source_id)),
                wait=True,
            )
        session.execute(
            delete(MemoryChunk).where(
                MemoryChunk.project_id == project_id,
                MemoryChunk.source_id == source_id,
            )
        )
        session.add_all(chunks)
        client.upsert(
            collection_name=collection_name,
            points=[
                models.PointStruct(
                    id=chunk.id,
                    vector=vector,
                    payload={
                        "project_id": project_id,
                        "conversation_id": conversation_id,
                        "source_type": source_type,
                        "source_id": source_id,
                        "content": chunk.content,
                    },
                )
                for chunk, vector in zip(chunks, vectors, strict=True)
            ],
            wait=True,
        )
        session.commit()
        return chunks

    @staticmethod
    def search(project_id: str, query: str, limit: int | None = None) -> list[MemorySearchResult]:
        client = get_qdrant_client()
        collection_name = _memory_collection_name()
        if not client.collection_exists(collection_name):
            return []
        vector = get_embedding_provider().embed_query(query)
        points = client.query_points(
            collection_name=collection_name,
            query=vector,
            query_filter=_memory_filter(project_id),
            limit=limit or settings.memory_retrieval_limit,
            with_payload=True,
        ).points
        return [
            MemorySearchResult(
                memory_id=point.id,
                score=point.score,
                source_type=point.payload["source_type"],
                source_id=point.payload["source_id"],
                conversation_id=point.payload.get("conversation_id"),
                content=point.payload["content"],
            )
            for point in points
            if point.payload is not None
        ]

    @staticmethod
    def stats(session: Session, project_id: str) -> MemoryStats:
        count = session.scalar(
            select(func.count(MemoryChunk.id)).where(MemoryChunk.project_id == project_id)
        )
        return MemoryStats(
            project_id=project_id,
            indexed_memories=count or 0,
            collection_name=_memory_collection_name(),
        )

    @staticmethod
    def forget_conversation(
        session: Session,
        project_id: str,
        conversation_id: str,
    ) -> None:
        client = get_qdrant_client()
        collection_name = _memory_collection_name()
        if client.collection_exists(collection_name):
            client.delete(
                collection_name=collection_name,
                points_selector=models.FilterSelector(
                    filter=_memory_filter(
                        project_id,
                        conversation_id=conversation_id,
                    )
                ),
                wait=True,
            )
        session.execute(
            delete(MemoryChunk).where(
                MemoryChunk.project_id == project_id,
                MemoryChunk.conversation_id == conversation_id,
            )
        )
        session.commit()


memory_service = MemoryService()
