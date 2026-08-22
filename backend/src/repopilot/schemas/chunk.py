from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ChunkingStatsResponse(BaseModel):
    project_id: UUID
    total_chunks: int
    total_chars: int
    strategy_breakdown: dict[str, int]


class KnowledgeChunkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_path: str
    chunk_index: int
    strategy: str
    content: str
    char_count: int
    start_line: int
    end_line: int
    symbol_name: str | None
    extra_metadata: dict[str, object]
    created_at: datetime
