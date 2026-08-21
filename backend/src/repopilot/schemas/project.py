from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

ProjectStatus = Literal["pending", "indexing", "ready", "failed"]


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    repository_url: HttpUrl
    default_branch: str = Field(default="main", min_length=1, max_length=120)


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    repository_url: str
    default_branch: str
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime
