import json
import logging
from collections.abc import Iterator
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from openai import APIError

from repopilot.db.session import SessionDep
from repopilot.schemas.rag import (
    RagAnswerResponse,
    RagAskRequest,
    RagRunDetail,
    RagRunSummary,
)
from repopilot.services.project_service import project_service
from repopilot.services.rag_run_service import rag_run_service
from repopilot.services.rag_service import (
    ChatConfigurationError,
    rag_service,
)
from repopilot.services.vector_search_service import (
    EmbeddingConfigurationError,
    VectorIndexNotReadyError,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _stream_event(event: dict[str, object]) -> str:
    """将一个结构化事件编码为浏览器可增量解析的 SSE 数据帧。"""
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
            detail="Repository must be ingested before asking questions",
        )
    return project


@router.post("/ask", response_model=RagAnswerResponse)
def ask_repository(
    project_id: UUID,
    payload: RagAskRequest,
    session: SessionDep,
) -> RagAnswerResponse:
    project = _get_ready_project(project_id, session)

    try:
        return rag_service.ask(
            session,
            project.id,
            payload.question,
            payload.retrieval_limit,
        )
    except (EmbeddingConfigurationError, ChatConfigurationError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Qwen API Key is not configured",
        ) from error
    except VectorIndexNotReadyError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Build the vector index before asking questions",
        ) from error
    except APIError as error:
        # 上游模型错误不应伪装成本地服务异常，返回 502 方便前端给出明确提示。
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Qwen API request failed",
        ) from error


@router.post("/stream", response_class=StreamingResponse)
def stream_repository_answer(
    project_id: UUID,
    payload: RagAskRequest,
    session: SessionDep,
) -> StreamingResponse:
    project = _get_ready_project(project_id, session)

    def events() -> Iterator[str]:
        try:
            for event in rag_service.stream(
                session,
                project.id,
                payload.question,
                payload.retrieval_limit,
            ):
                yield _stream_event(event)
        except (EmbeddingConfigurationError, ChatConfigurationError):
            yield _stream_error("Qwen API Key 尚未配置。")
        except VectorIndexNotReadyError:
            yield _stream_error("请先构建向量索引。")
        except APIError:
            # SSE 响应一旦开始就不能再改成 502，因此用 error 事件通知前端。
            logger.exception("Qwen streaming request failed")
            yield _stream_error("Qwen 流式回答生成失败，请检查模型名称或稍后重试。")
        except Exception:
            logger.exception("Unexpected RAG streaming error")
            yield _stream_error("RAG 流式处理发生异常，请查看后端日志。")

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/runs", response_model=list[RagRunSummary])
def list_repository_runs(
    project_id: UUID,
    session: SessionDep,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[RagRunSummary]:
    _get_ready_project(project_id, session)
    return rag_run_service.list(session, str(project_id), offset, limit)


@router.get("/runs/{run_id}", response_model=RagRunDetail)
def get_repository_run(
    project_id: UUID,
    run_id: UUID,
    session: SessionDep,
) -> RagRunDetail:
    _get_ready_project(project_id, session)
    run = rag_run_service.get(session, str(project_id), str(run_id))
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="RAG run not found")
    return run
