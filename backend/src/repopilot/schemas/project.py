from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

ProjectStatus = Literal["pending", "indexing", "ready", "failed"]


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    repository_url: HttpUrl
    default_branch: str = Field(
        default="main",
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*$",
    )

    @field_validator("default_branch")
    @classmethod
    def validate_branch_name(cls, value: str) -> str:
        # 禁止 Git 分支中的父路径片段，避免把不可信输入传给克隆命令。
        if ".." in value or "//" in value:
            raise ValueError("Invalid Git branch name")
        return value

    @field_validator("repository_url")
    @classmethod
    def validate_github_url(cls, value: HttpUrl) -> HttpUrl:
        # 第一版仅允许公开 GitHub 仓库，避免任意 URL 被 Git 当作远程源访问。
        if value.scheme != "https" or value.query is not None or value.fragment is not None:
            raise ValueError("Repository URL must be a plain HTTPS URL")
        if value.host not in {"github.com", "www.github.com"}:
            raise ValueError("Only GitHub repository URLs are supported")
        if len(value.path.strip("/").split("/")) != 2:
            raise ValueError("URL must point to a GitHub owner/repository")
        return value


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    repository_url: str
    default_branch: str
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime
