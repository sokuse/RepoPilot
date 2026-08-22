from uuid import UUID

from pydantic import BaseModel


class RepositoryStatsResponse(BaseModel):
    project_id: UUID
    total_files: int
    total_bytes: int
    language_breakdown: dict[str, int]
