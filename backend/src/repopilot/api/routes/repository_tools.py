import json
from uuid import UUID

from fastapi import APIRouter, HTTPException

from repopilot.db.session import SessionDep
from repopilot.schemas.repository_tool import (
    RepositoryFileReadRequest,
    RepositoryFileReadResponse,
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
