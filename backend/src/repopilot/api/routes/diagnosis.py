from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from openai import APIError

from repopilot.db.session import SessionDep
from repopilot.schemas.diagnosis import (
    DiagnosisRequest,
    DiagnosisResponse,
    MultiAgentDiagnosisResponse,
)
from repopilot.services.diagnosis_service import diagnosis_service
from repopilot.services.multi_agent_diagnosis_service import multi_agent_diagnosis_service
from repopilot.services.project_service import project_service
from repopilot.services.rag_service import ChatConfigurationError
from repopilot.services.vector_search_service import (
    EmbeddingConfigurationError,
    VectorIndexNotReadyError,
)

router = APIRouter()


def _get_ready_project(project_id: UUID, session: SessionDep):
    project = project_service.get(session, str(project_id))
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if project.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Repository must be ingested before diagnosis",
        )
    return project


@router.post("", response_model=DiagnosisResponse)
def diagnose_repository(
    project_id: UUID,
    payload: DiagnosisRequest,
    session: SessionDep,
) -> DiagnosisResponse:
    project = _get_ready_project(project_id, session)
    try:
        return diagnosis_service.diagnose(
            session,
            project.id,
            payload.question,
            payload.max_iterations,
        )
    except (EmbeddingConfigurationError, ChatConfigurationError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Qwen API Key is not configured",
        ) from error
    except VectorIndexNotReadyError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Build the vector index before diagnosis",
        ) from error
    except APIError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Qwen tool-calling request failed",
        ) from error


@router.post("/multi-agent", response_model=MultiAgentDiagnosisResponse)
def diagnose_repository_with_multiple_agents(
    project_id: UUID,
    payload: DiagnosisRequest,
    session: SessionDep,
) -> MultiAgentDiagnosisResponse:
    project = _get_ready_project(project_id, session)
    try:
        return multi_agent_diagnosis_service.diagnose(
            session,
            project.id,
            payload.question,
            payload.max_iterations,
        )
    except (EmbeddingConfigurationError, ChatConfigurationError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Qwen API Key is not configured",
        ) from error
    except VectorIndexNotReadyError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Build the vector index before diagnosis",
        ) from error
    except APIError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Qwen multi-agent request failed",
        ) from error
