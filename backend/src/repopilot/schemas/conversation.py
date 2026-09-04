from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ConversationCreate(BaseModel):
    title: str = Field(default="新对话", min_length=1, max_length=120)


class ConversationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_id: UUID
    role: Literal["user", "assistant"]
    content: str
    rag_run_id: UUID | None
    feedback: Literal["helpful", "unhelpful"] | None
    feedback_note: str | None
    created_at: datetime


class ConversationDetail(ConversationSummary):
    messages: list[ConversationMessageResponse]


class MessageFeedbackRequest(BaseModel):
    feedback: Literal["helpful", "unhelpful"]
    note: str | None = Field(default=None, max_length=1000)


class MemorySearchResult(BaseModel):
    memory_id: UUID
    score: float
    source_type: Literal["conversation", "diagnosis"]
    source_id: str
    conversation_id: UUID | None
    content: str


class MemoryStats(BaseModel):
    project_id: UUID
    indexed_memories: int
    collection_name: str


class MemorySearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=2000)
    limit: int = Field(default=4, ge=1, le=10)
