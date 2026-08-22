from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Response, status

from repopilot.db.session import SessionDep
from repopilot.schemas.ingestion import RepositoryStatsResponse
from repopilot.schemas.project import ProjectCreate, ProjectResponse
from repopilot.services.project_service import DuplicateRepositoryError, project_service
from repopilot.services.repository_ingestion_service import (
    remove_repository_checkout,
    repository_ingestion_service,
    run_repository_ingestion,
)

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


@router.post(
    "/{project_id}/ingest",
    response_model=ProjectResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_repository_ingestion(
    project_id: UUID,
    background_tasks: BackgroundTasks,
    session: SessionDep,
) -> ProjectResponse:
    project = project_service.get(session, str(project_id))
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if project.status == "indexing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Repository ingestion is already running",
        )
    if project.status == "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Repository has already been ingested",
        )

    project = repository_ingestion_service.start(session, project)
    # 先返回 202，克隆和扫描在响应之后执行，避免长时间阻塞 HTTP 请求。
    background_tasks.add_task(run_repository_ingestion, project.id)
    return project


@router.get("/{project_id}/stats", response_model=RepositoryStatsResponse)
def get_repository_stats(project_id: UUID, session: SessionDep) -> RepositoryStatsResponse:
    project = project_service.get(session, str(project_id))
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return repository_ingestion_service.stats(session, project.id)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: UUID, session: SessionDep) -> Response:
    project = project_service.get(session, str(project_id))
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    # 数据库记录和本地克隆目录属于同一个项目，删除时一起清理。
    remove_repository_checkout(project.id)
    project_service.delete(session, project)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
