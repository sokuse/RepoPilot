from fastapi import APIRouter, status

from repopilot.schemas.project import ProjectCreate, ProjectResponse
from repopilot.services.project_service import project_service

router = APIRouter()


@router.get("", response_model=list[ProjectResponse])
def list_projects() -> list[ProjectResponse]:
    return project_service.list()


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate) -> ProjectResponse:
    return project_service.create(payload)

