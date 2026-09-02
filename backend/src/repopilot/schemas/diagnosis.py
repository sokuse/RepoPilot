from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from repopilot.schemas.rag import RagTokenUsage


class DiagnosisRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    max_iterations: int = Field(default=3, ge=2, le=5)


class ToolCallTrace(BaseModel):
    """一次 Function Call 的入参、结果摘要和执行指标。"""

    call_id: str
    name: str
    arguments: dict[str, Any]
    summary: str
    result: str
    success: bool
    duration_ms: int


class DiagnosisResponse(BaseModel):
    project_id: UUID
    question: str
    answer: str
    model: str
    iterations: int
    duration_ms: int
    usage: RagTokenUsage
    tool_calls: list[ToolCallTrace]
    warnings: list[str]
