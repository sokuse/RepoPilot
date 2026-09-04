import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status

from repopilot.db.session import SessionDep
from repopilot.schemas.conversation import (
    ConversationCreate,
    ConversationDetail,
    ConversationMessageResponse,
    ConversationSummary,
    MemorySearchRequest,
    MemorySearchResult,
    MemoryStats,
    MessageFeedbackRequest,
)
from repopilot.services.conversation_service import conversation_service
from repopilot.services.memory_service import memory_service
from repopilot.services.project_service import project_service

router = APIRouter()
logger = logging.getLogger(__name__)


def _require_project(project_id: UUID, session: SessionDep) -> str:
    project = project_service.get(session, str(project_id))
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project.id


@router.post("", response_model=ConversationSummary, status_code=status.HTTP_201_CREATED)
def create_conversation(
    project_id: UUID, payload: ConversationCreate, session: SessionDep
) -> ConversationSummary:
    project_id_value = _require_project(project_id, session)
    return conversation_service.create(session, project_id_value, payload.title)


@router.get("", response_model=list[ConversationSummary])
def list_conversations(project_id: UUID, session: SessionDep) -> list[ConversationSummary]:
    return conversation_service.list(session, _require_project(project_id, session))


@router.get("/memory/stats", response_model=MemoryStats)
def get_memory_stats(project_id: UUID, session: SessionDep) -> MemoryStats:
    return memory_service.stats(session, _require_project(project_id, session))


@router.post("/memory/search", response_model=list[MemorySearchResult])
def search_memories(
    project_id: UUID,
    payload: MemorySearchRequest,
    session: SessionDep,
) -> list[MemorySearchResult]:
    project_id_value = _require_project(project_id, session)
    return memory_service.search(project_id_value, payload.query, payload.limit)


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    project_id: UUID, conversation_id: UUID, session: SessionDep
) -> ConversationDetail:
    detail = conversation_service.detail(
        session,
        _require_project(project_id, session),
        str(conversation_id),
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return detail


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(project_id: UUID, conversation_id: UUID, session: SessionDep) -> Response:
    conversation = conversation_service.get(
        session, _require_project(project_id, session), str(conversation_id)
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    memory_service.forget_conversation(session, conversation.project_id, conversation.id)
    conversation_service.delete(session, conversation)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/{conversation_id}/messages/{message_id}/feedback",
    response_model=ConversationMessageResponse,
)
def set_message_feedback(
    project_id: UUID,
    conversation_id: UUID,
    message_id: UUID,
    payload: MessageFeedbackRequest,
    session: SessionDep,
) -> ConversationMessageResponse:
    conversation = conversation_service.get(
        session, _require_project(project_id, session), str(conversation_id)
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    message = conversation_service.set_feedback(
        session, str(conversation_id), str(message_id), payload.feedback, payload.note
    )
    if message is None:
        raise HTTPException(status_code=404, detail="Assistant message not found")
    try:
        memory_service.remember(
            session,
            conversation.project_id,
            "conversation",
            message.id,
            conversation_service.memory_text(session, message),
            conversation.id,
        )
    except Exception:
        # 反馈已经写入 SQLite，向量更新失败不应让用户误以为反馈没有保存。
        logger.exception("Failed to refresh memory after feedback")
    return ConversationMessageResponse.model_validate(message)
