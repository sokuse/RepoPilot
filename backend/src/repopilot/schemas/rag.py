from uuid import UUID

from pydantic import BaseModel, Field

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


class RagAnswerResponse(BaseModel):
    project_id: UUID
    question: str
    answer: str
    citations: list[RagCitation]
    retrieved_chunks: list[SemanticSearchResult]
    steps: list[RagExecutionStep]
    warnings: list[str]
