from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from repopilot.core.config import settings
from repopilot.models.rag_run import RagRun
from repopilot.schemas.rag import RagAnswerResponse, RagRunDetail, RagRunSummary


class RagRunService:
    @staticmethod
    def start(
        session: Session,
        project_id: str,
        question: str,
        retrieval_limit: int,
    ) -> RagRun:
        run = RagRun(
            project_id=project_id,
            question=question,
            status="running",
            chat_model=settings.chat_model_name,
            embedding_model=settings.embedding_model_name,
            retrieval_limit=retrieval_limit,
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        return run

    @staticmethod
    def complete(
        session: Session,
        run_id: str,
        response: RagAnswerResponse,
    ) -> RagRun:
        run = session.get(RagRun, run_id)
        if run is None:
            raise RuntimeError("RAG run disappeared before completion")
        run.answer = response.answer
        run.status = "completed"
        run.retrieved_count = len(response.retrieved_chunks)
        run.citation_count = len(response.citations)
        run.prompt_tokens = response.usage.prompt_tokens
        run.completion_tokens = response.usage.completion_tokens
        run.total_tokens = response.usage.total_tokens
        run.duration_ms = response.duration_ms
        run.retrieved_chunks = [item.model_dump(mode="json") for item in response.retrieved_chunks]
        run.citations = [item.model_dump(mode="json") for item in response.citations]
        run.steps = [item.model_dump(mode="json") for item in response.steps]
        run.warnings = response.warnings
        run.completed_at = datetime.now(UTC)
        session.commit()
        session.refresh(run)
        return run

    @staticmethod
    def fail(session: Session, run_id: str, error: Exception, duration_ms: int) -> None:
        # 上游异常可能使当前事务失效，先回滚再更新已经单独提交的运行记录。
        session.rollback()
        run = session.get(RagRun, run_id)
        if run is None:
            return
        run.status = "failed"
        run.duration_ms = duration_ms
        run.error_message = f"{type(error).__name__}: {str(error)}"[:1000]
        run.completed_at = datetime.now(UTC)
        session.commit()

    @staticmethod
    def list(
        session: Session,
        project_id: str,
        offset: int,
        limit: int,
    ) -> list[RagRunSummary]:
        rows = session.scalars(
            select(RagRun)
            .where(RagRun.project_id == project_id)
            .order_by(RagRun.created_at.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        return [RagRunSummary.model_validate(row) for row in rows]

    @staticmethod
    def get(session: Session, project_id: str, run_id: str) -> RagRunDetail | None:
        row = session.scalar(
            select(RagRun).where(RagRun.id == run_id, RagRun.project_id == project_id)
        )
        return RagRunDetail.model_validate(row) if row else None


rag_run_service = RagRunService()
