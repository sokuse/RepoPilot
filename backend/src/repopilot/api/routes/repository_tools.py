import json
from uuid import UUID

from fastapi import APIRouter, HTTPException

from repopilot.db.session import SessionDep
from repopilot.schemas.repository_tool import (
    RepositoryFileReadRequest,
    RepositoryFileReadResponse,
    RepositoryGrepRequest,
    RepositoryGrepResponse,
)
from repopilot.services.project_service import project_service
from repopilot.services.repository_tool_service import repository_tool_service

router = APIRouter()


@router.post("/read-file", response_model=RepositoryFileReadResponse)
def read_repository_file(
    project_id: UUID,
    payload: RepositoryFileReadRequest,
    session: SessionDep,
) -> RepositoryFileReadResponse:
    project = project_service.get(session, str(project_id))
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.status != "ready":
        raise HTTPException(status_code=409, detail="Repository must be ready before reading files")
    execution = repository_tool_service.execute(
        session,
        project.id,
        "api-read-file",
        "read_file",
        payload.model_dump(),
    )
    if not execution.trace.success:
        raise HTTPException(status_code=422, detail=execution.trace.summary)
    return RepositoryFileReadResponse(project_id=project.id, **json.loads(execution.model_content))


@router.post("/grep", response_model=RepositoryGrepResponse)
def grep_repository(
    project_id: UUID,
    payload: RepositoryGrepRequest,
    session: SessionDep,
) -> RepositoryGrepResponse:
    """让用户和 Agent 复用同一套仓库精确搜索逻辑。"""
    project = project_service.get(session, str(project_id))
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.status != "ready":
        raise HTTPException(status_code=409, detail="Repository must be ready before searching")
    execution = repository_tool_service.execute(
        session,
        project.id,
        "api-grep",
        "grep_repository",
        payload.model_dump(),
    )
    if not execution.trace.success:
        raise HTTPException(status_code=422, detail=execution.trace.summary)
    return RepositoryGrepResponse(project_id=project.id, **json.loads(execution.model_content))
