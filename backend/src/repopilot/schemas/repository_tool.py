from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class RepositoryFileReadRequest(BaseModel):
    path: str = Field(min_length=1, max_length=1000)
    start_line: int = Field(default=1, ge=1)
    end_line: int = Field(default=200, ge=1)

    @model_validator(mode="after")
    def validate_range(self) -> "RepositoryFileReadRequest":
        if self.end_line < self.start_line:
            raise ValueError("end_line must not be smaller than start_line")
        if self.end_line - self.start_line > 199:
            raise ValueError("a single read may contain at most 200 lines")
        return self


class RepositoryFileReadResponse(BaseModel):
    project_id: UUID
    path: str
    start_line: int
    end_line: int
    content: str
    truncated: bool


class RepositoryGrepRequest(BaseModel):
    pattern: str = Field(min_length=1, max_length=200)
    path_prefix: str = Field(default="", max_length=500)
    case_sensitive: bool = False
    limit: int = Field(default=20, ge=1, le=50)


class RepositoryGrepMatch(BaseModel):
    path: str
    line_number: int
    column: int
    line: str


class RepositoryGrepResponse(BaseModel):
    project_id: UUID
    pattern: str
    path_prefix: str
    case_sensitive: bool
    count: int
    matches: list[RepositoryGrepMatch]
    truncated: bool
