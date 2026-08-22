from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from repopilot.db.session import SessionDep
from repopilot.schemas.chunk import ChunkingStatsResponse, KnowledgeChunkResponse
from repopilot.services.chunking_service import chunking_service
from repopilot.services.project_service import project_service

router = APIRouter()


def _get_ready_project(project_id: UUID, session: SessionDep):
    project = project_service.get(session, str(project_id))
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if project.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Repository must be ingested before chunking",
        )
    return project


@router.post("", response_model=ChunkingStatsResponse)
def rebuild_chunks(project_id: UUID, session: SessionDep) -> ChunkingStatsResponse:
    project = _get_ready_project(project_id, session)
    # 当前仓库规模较小时同步完成，调用方拿到响应即可确认切片已经持久化。
    return chunking_service.rebuild(session, project)


@router.get("/stats", response_model=ChunkingStatsResponse)
def get_chunk_stats(project_id: UUID, session: SessionDep) -> ChunkingStatsResponse:
    project = _get_ready_project(project_id, session)
    return chunking_service.stats(session, project.id)


@router.get("", response_model=list[KnowledgeChunkResponse])
def list_chunks(
    project_id: UUID,
    session: SessionDep,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[KnowledgeChunkResponse]:
    project = _get_ready_project(project_id, session)
    return chunking_service.list(session, project.id, offset, limit)
