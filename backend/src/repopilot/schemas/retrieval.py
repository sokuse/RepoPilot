from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class VectorIndexStatsResponse(BaseModel):
    project_id: UUID
    ready: bool
    embedding_model: str
    vector_size: int
    indexed_chunks: int
    indexed_at: datetime | None


class SemanticSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=1000)
    limit: int = Field(default=5, ge=1, le=20)
    score_threshold: float | None = Field(default=None, ge=0, le=1)


class SemanticSearchResult(BaseModel):
    chunk_id: UUID
    score: float
    source_path: str
    start_line: int
    end_line: int
    symbol_name: str | None
    strategy: str
    content: str


class SemanticSearchResponse(BaseModel):
    project_id: UUID
    query: str
    results: list[SemanticSearchResult]
