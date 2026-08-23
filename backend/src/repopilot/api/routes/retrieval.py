from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from repopilot.db.session import SessionDep
from repopilot.schemas.retrieval import (
    SemanticSearchRequest,
    SemanticSearchResponse,
    VectorIndexStatsResponse,
)
from repopilot.services.project_service import project_service
from repopilot.services.vector_search_service import (
    EmbeddingConfigurationError,
    EmptyKnowledgeBaseError,
    VectorIndexNotReadyError,
    vector_search_service,
)

router = APIRouter()


def _get_ready_project(project_id: UUID, session: SessionDep):
    project = project_service.get(session, str(project_id))
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if project.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Repository must be ingested before indexing",
        )
    return project


@router.get("/stats", response_model=VectorIndexStatsResponse)
def get_vector_index_stats(
    project_id: UUID, session: SessionDep
) -> VectorIndexStatsResponse:
    project = _get_ready_project(project_id, session)
    return vector_search_service.stats(session, project.id)


@router.post("", response_model=VectorIndexStatsResponse)
def rebuild_vector_index(
    project_id: UUID, session: SessionDep
) -> VectorIndexStatsResponse:
    project = _get_ready_project(project_id, session)
    try:
        return vector_search_service.rebuild(session, project.id)
    except EmbeddingConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Embedding API Key is not configured",
        ) from error
    except EmptyKnowledgeBaseError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Generate knowledge chunks before building the vector index",
        ) from error


@router.post("/search", response_model=SemanticSearchResponse)
def semantic_search(
    project_id: UUID,
    payload: SemanticSearchRequest,
    session: SessionDep,
) -> SemanticSearchResponse:
    project = _get_ready_project(project_id, session)
    try:
        return vector_search_service.search(
            session,
            project.id,
            payload.query,
            payload.limit,
            payload.score_threshold,
        )
    except EmbeddingConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Embedding API Key is not configured",
        ) from error
    except VectorIndexNotReadyError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Build the vector index before searching",
        ) from error
