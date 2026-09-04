from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

EvaluationMode = Literal["retrieval", "rag", "single_agent", "multi_agent"]


class EvaluationCaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=2, max_length=2000)
    expected_files: list[str] = Field(min_length=1, max_length=20)
    required_keywords: list[str] = Field(min_length=1, max_length=30)

    @field_validator("expected_files", "required_keywords")
    @classmethod
    def clean_items(cls, values: list[str]) -> list[str]:
        # 去掉空白和重复项，避免同一个期望值被重复计分。
        cleaned = list(dict.fromkeys(value.strip() for value in values if value.strip()))
        if not cleaned:
            raise ValueError("至少需要一个非空值")
        return cleaned


class EvaluationCaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    question: str
    expected_files: list[str]
    required_keywords: list[str]
    created_at: datetime
    updated_at: datetime


class EvaluationRunCreate(BaseModel):
    name: str = Field(default="评测实验", min_length=1, max_length=200)
    mode: EvaluationMode = "rag"
    case_ids: list[UUID] = Field(default_factory=list, max_length=50)
    retrieval_limit: int = Field(default=8, ge=3, le=12)
    max_iterations: int = Field(default=3, ge=2, le=5)


class EvaluationResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: UUID
    case_id: UUID | None
    case_name: str
    question: str
    expected_files: list[str]
    required_keywords: list[str]
    answer: str
    retrieved_files: list[str]
    retrieval_score: float
    keyword_score: float
    evidence_score: float
    overall_score: float
    passed: bool
    total_tokens: int
    duration_ms: int
    error_message: str | None


class EvaluationRunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    mode: EvaluationMode
    status: str
    chat_model: str
    embedding_model: str
    chunk_strategies: list[str]
    case_count: int
    passed_count: int
    average_retrieval_score: float
    average_keyword_score: float
    average_evidence_score: float
    average_overall_score: float
    total_tokens: int
    duration_ms: int
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None


class EvaluationRunDetail(EvaluationRunSummary):
    results: list[EvaluationResultResponse]
