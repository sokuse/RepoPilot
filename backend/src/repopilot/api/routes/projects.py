from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status

from repopilot.db.session import SessionDep
from repopilot.schemas.project import ProjectCreate, ProjectResponse
from repopilot.services.project_service import DuplicateRepositoryError, project_service

router = APIRouter()


@router.get("", response_model=list[ProjectResponse])
def list_projects(session: SessionDep) -> list[ProjectResponse]:
    return project_service.list(session)


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project_id: UUID, session: SessionDep) -> ProjectResponse:
    project = project_service.get(session, str(project_id))
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, session: SessionDep) -> ProjectResponse:
    try:
        return project_service.create(session, payload)
    except DuplicateRepositoryError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Repository has already been registered",
        ) from error


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: UUID, session: SessionDep) -> Response:
    project = project_service.get(session, str(project_id))
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    project_service.delete(session, project)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
