from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from repopilot.schemas.retrieval import SemanticSearchResult


class RagAskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    retrieval_limit: int = Field(default=8, ge=3, le=12)


class RagCitation(BaseModel):
    source_id: str
    chunk_id: UUID
    source_path: str
    start_line: int
    end_line: int
    symbol_name: str | None
    score: float


class RagExecutionStep(BaseModel):
    name: str
    label: str
    detail: str


class RagTokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class RagAnswerResponse(BaseModel):
    run_id: UUID | None = None
    project_id: UUID
    question: str
    answer: str
    citations: list[RagCitation]
    retrieved_chunks: list[SemanticSearchResult]
    steps: list[RagExecutionStep]
    warnings: list[str]
    usage: RagTokenUsage = Field(default_factory=RagTokenUsage)
    duration_ms: int = 0


class RagRunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    question: str
    status: str
    chat_model: str
    embedding_model: str
    retrieval_limit: int
    retrieved_count: int
    citation_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    duration_ms: int
    created_at: datetime
    completed_at: datetime | None


class RagRunDetail(RagRunSummary):
    answer: str
    retrieved_chunks: list[SemanticSearchResult]
    citations: list[RagCitation]
    steps: list[RagExecutionStep]
    warnings: list[str]
    error_message: str | None
