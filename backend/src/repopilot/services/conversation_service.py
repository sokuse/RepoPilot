from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from repopilot.models.conversation import Conversation, ConversationMessage
from repopilot.schemas.conversation import ConversationDetail, ConversationSummary


class ConversationService:
    @staticmethod
    def create(session: Session, project_id: str, title: str) -> ConversationSummary:
        conversation = Conversation(project_id=project_id, title=title.strip() or "新对话")
        session.add(conversation)
        session.commit()
        session.refresh(conversation)
        return ConversationSummary.model_validate(conversation)

    @staticmethod
    def list(session: Session, project_id: str) -> list[ConversationSummary]:
        rows = session.scalars(
            select(Conversation)
            .where(Conversation.project_id == project_id)
            .order_by(Conversation.updated_at.desc())
        ).all()
        return [ConversationSummary.model_validate(row) for row in rows]

    @staticmethod
    def get(session: Session, project_id: str, conversation_id: str) -> Conversation | None:
        return session.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.project_id == project_id,
            )
        )

    def detail(
        self, session: Session, project_id: str, conversation_id: str
    ) -> ConversationDetail | None:
        conversation = self.get(session, project_id, conversation_id)
        if conversation is None:
            return None
        messages = session.scalars(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.created_at, ConversationMessage.id)
        ).all()
        return ConversationDetail(
            **ConversationSummary.model_validate(conversation).model_dump(),
            messages=list(messages),
        )

    def add_message(
        self,
        session: Session,
        conversation_id: str,
        role: str,
        content: str,
        rag_run_id: str | None = None,
    ) -> ConversationMessage:
        message = ConversationMessage(
            conversation_id=conversation_id,
            role=role,
            content=content,
            rag_run_id=rag_run_id,
        )
        conversation = session.get(Conversation, conversation_id)
        if conversation is None:
            raise ValueError("Conversation not found")
        # 第一条用户消息自动成为标题，列表中比“新对话”更容易辨认。
        if role == "user" and conversation.title == "新对话":
            conversation.title = content.strip()[:120]
        conversation.updated_at = datetime.now(UTC)
        session.add(message)
        session.commit()
        session.refresh(message)
        return message

    @staticmethod
    def recent_messages(
        session: Session,
        conversation_id: str,
        limit: int,
    ) -> list[ConversationMessage]:
        # 先倒序取最近消息，再恢复为正常对话顺序交给模型。
        rows = session.scalars(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.created_at.desc(), ConversationMessage.id.desc())
            .limit(limit)
        ).all()
        return list(reversed(rows))

    @staticmethod
    def delete(session: Session, conversation: Conversation) -> None:
        session.delete(conversation)
        session.commit()

    @staticmethod
    def set_feedback(
        session: Session,
        conversation_id: str,
        message_id: str,
        feedback: str,
        note: str | None,
    ) -> ConversationMessage | None:
        message = session.scalar(
            select(ConversationMessage).where(
                ConversationMessage.id == message_id,
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.role == "assistant",
            )
        )
        if message is None:
            return None
        message.feedback = feedback
        message.feedback_note = note
        session.commit()
        session.refresh(message)
        return message

    @staticmethod
    def memory_text(session: Session, message: ConversationMessage) -> str:
        user_message = session.scalar(
            select(ConversationMessage)
            .where(
                ConversationMessage.conversation_id == message.conversation_id,
                ConversationMessage.role == "user",
                ConversationMessage.created_at <= message.created_at,
            )
            .order_by(ConversationMessage.created_at.desc(), ConversationMessage.id.desc())
            .limit(1)
        )
        feedback = ""
        if message.feedback:
            label = "用户认为有帮助" if message.feedback == "helpful" else "用户认为没有帮助"
            feedback = f"\n反馈：{label}"
            if message.feedback_note:
                feedback += f"；{message.feedback_note}"
        question = user_message.content if user_message else "未知问题"
        return f"用户问题：{question}\n助手回答：{message.content}{feedback}"


conversation_service = ConversationService()
