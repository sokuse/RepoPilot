import json
import logging
from collections.abc import Iterator
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from openai import APIError

from repopilot.db.session import SessionDep
from repopilot.schemas.diagnosis import (
    DiagnosisRequest,
    DiagnosisResponse,
    MultiAgentDiagnosisResponse,
)
from repopilot.services.diagnosis_service import EmptyDiagnosisAnswerError, diagnosis_service
from repopilot.services.memory_service import memory_service
from repopilot.services.multi_agent_diagnosis_service import multi_agent_diagnosis_service
from repopilot.services.project_service import project_service
from repopilot.services.rag_service import ChatConfigurationError
from repopilot.services.vector_search_service import (
    EmbeddingConfigurationError,
    VectorIndexNotReadyError,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _stream_event(event: dict[str, object]) -> str:
    data = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    return f"data: {data}\n\n"


def _stream_error(message: str) -> str:
    return _stream_event({"type": "error", "message": message})


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


def _remember_diagnosis(
    session: SessionDep,
    project_id: str,
    question: str,
    answer: str,
) -> None:
    try:
        memory_service.remember(
            session,
            project_id,
            "diagnosis",
            str(uuid4()),
            f"诊断问题：{question}\n诊断结论：{answer}",
        )
    except Exception:
        # 长期记忆属于增强能力，索引失败不能覆盖已经成功生成的诊断结果。
        logger.exception("Failed to index diagnosis memory")


@router.post("", response_model=DiagnosisResponse)
def diagnose_repository(
    project_id: UUID,
    payload: DiagnosisRequest,
    session: SessionDep,
) -> DiagnosisResponse:
    project = _get_ready_project(project_id, session)
    try:
        response = diagnosis_service.diagnose(
            session,
            project.id,
            payload.question,
            payload.max_iterations,
        )
        _remember_diagnosis(session, project.id, payload.question, response.answer)
        return response
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
    except EmptyDiagnosisAnswerError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Qwen did not return a diagnosis after retrying",
        ) from error


@router.post("/multi-agent", response_model=MultiAgentDiagnosisResponse)
def diagnose_repository_with_multiple_agents(
    project_id: UUID,
    payload: DiagnosisRequest,
    session: SessionDep,
) -> MultiAgentDiagnosisResponse:
    project = _get_ready_project(project_id, session)
    try:
        response = multi_agent_diagnosis_service.diagnose(
            session,
            project.id,
            payload.question,
            payload.max_iterations,
        )
        _remember_diagnosis(session, project.id, payload.question, response.final_answer)
        return response
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
        logger.exception("Core investigator Agent request failed during multi-agent diagnosis")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Qwen multi-agent request failed",
        ) from error


@router.post("/stream", response_class=StreamingResponse)
def stream_repository_diagnosis(
    project_id: UUID,
    payload: DiagnosisRequest,
    session: SessionDep,
) -> StreamingResponse:
    project = _get_ready_project(project_id, session)

    def events() -> Iterator[str]:
        try:
            for event in diagnosis_service.stream(
                session,
                project.id,
                payload.question,
                payload.max_iterations,
            ):
                if event.get("type") == "complete":
                    response = event.get("response", {})
                    if isinstance(response, dict):
                        answer = response.get("answer")
                        if isinstance(answer, str):
                            _remember_diagnosis(
                                session, project.id, payload.question, answer
                            )
                yield _stream_event(event)
        except (EmbeddingConfigurationError, ChatConfigurationError):
            yield _stream_error("Qwen API Key 尚未配置。")
        except VectorIndexNotReadyError:
            yield _stream_error("请先构建向量索引。")
        except APIError:
            logger.exception("Qwen diagnosis streaming request failed")
            yield _stream_error("Qwen 智能诊断失败，请检查模型配置或稍后重试。")
        except EmptyDiagnosisAnswerError:
            logger.exception("Qwen returned an empty diagnosis after retrying")
            yield _stream_error("Qwen 未返回诊断结论，系统自动重试后仍然为空。")
        except Exception:
            logger.exception("Unexpected diagnosis streaming error")
            yield _stream_error("智能诊断发生异常，请查看后端日志。")

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
