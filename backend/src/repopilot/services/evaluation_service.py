import json
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from repopilot.core.config import settings
from repopilot.models.evaluation import EvaluationCase, EvaluationResult, EvaluationRun
from repopilot.models.knowledge_chunk import KnowledgeChunk
from repopilot.schemas.diagnosis import ToolCallTrace
from repopilot.schemas.evaluation import (
    EvaluationCaseCreate,
    EvaluationRunCreate,
    EvaluationRunDetail,
    EvaluationRunSummary,
)
from repopilot.services.diagnosis_service import diagnosis_service
from repopilot.services.multi_agent_diagnosis_service import multi_agent_diagnosis_service
from repopilot.services.rag_service import rag_service
from repopilot.services.vector_search_service import vector_search_service


def _normalized_path(value: str) -> str:
    return value.replace("\\", "/").removeprefix("./").strip("/").lower()


def _file_matches(expected: str, actual: str) -> bool:
    expected_path = _normalized_path(expected)
    actual_path = _normalized_path(actual)
    return actual_path == expected_path or actual_path.endswith(f"/{expected_path}")


def _percentage(matched: int, total: int) -> float:
    return round(matched / total * 100, 2) if total else 100.0


def _collect_paths(value: Any, paths: set[str]) -> None:
    """从 Function Call 的 JSON 结果中递归提取文件路径。"""
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"path", "source_path", "file_path"} and isinstance(item, str):
                paths.add(item)
            else:
                _collect_paths(item, paths)
    elif isinstance(value, list):
        for item in value:
            _collect_paths(item, paths)


def _tool_evidence(tool_calls: list[ToolCallTrace]) -> tuple[list[str], float]:
    paths: set[str] = set()
    successful = 0
    for call in tool_calls:
        if call.success:
            successful += 1
        path_argument = call.arguments.get("path")
        if isinstance(path_argument, str):
            paths.add(path_argument)
        try:
            _collect_paths(json.loads(call.result), paths)
        except (json.JSONDecodeError, TypeError):
            # 某些工具返回的是纯文本；路径参数仍然可以作为追溯依据。
            pass
    return sorted(paths), _percentage(successful, len(tool_calls)) if tool_calls else 0.0


class EvaluationService:
    @staticmethod
    def create_case(
        session: Session, project_id: str, payload: EvaluationCaseCreate
    ) -> EvaluationCase:
        case = EvaluationCase(project_id=project_id, **payload.model_dump())
        session.add(case)
        session.commit()
        session.refresh(case)
        return case

    @staticmethod
    def list_cases(session: Session, project_id: str) -> list[EvaluationCase]:
        return list(
            session.scalars(
                select(EvaluationCase)
                .where(EvaluationCase.project_id == project_id)
                .order_by(EvaluationCase.created_at.desc())
            ).all()
        )

    @staticmethod
    def delete_case(session: Session, project_id: str, case_id: str) -> bool:
        case = session.scalar(
            select(EvaluationCase).where(
                EvaluationCase.id == case_id, EvaluationCase.project_id == project_id
            )
        )
        if case is None:
            return False
        session.delete(case)
        session.commit()
        return True

    @staticmethod
    def _selected_cases(
        session: Session, project_id: str, case_ids: list[str]
    ) -> list[EvaluationCase]:
        statement = select(EvaluationCase).where(EvaluationCase.project_id == project_id)
        if case_ids:
            statement = statement.where(EvaluationCase.id.in_(case_ids))
        return list(session.scalars(statement.order_by(EvaluationCase.created_at)).all())

    @staticmethod
    def _chunk_strategies(session: Session, project_id: str) -> list[str]:
        return list(
            session.scalars(
                select(distinct(KnowledgeChunk.strategy))
                .where(KnowledgeChunk.project_id == project_id)
                .order_by(KnowledgeChunk.strategy)
            ).all()
        )

    @staticmethod
    def _execute_case(
        session: Session,
        project_id: str,
        case: EvaluationCase,
        payload: EvaluationRunCreate,
    ) -> tuple[str, list[str], float, int, int]:
        """执行一种被测方案，统一返回答案、证据文件、证据分、Token 和耗时。"""
        started = perf_counter()
        if payload.mode == "retrieval":
            response = vector_search_service.search(
                session, project_id, case.question, payload.retrieval_limit, None
            )
            return (
                "",
                [item.source_path for item in response.results],
                100.0,
                0,
                int((perf_counter() - started) * 1000),
            )

        if payload.mode == "rag":
            response = rag_service.ask(
                session, project_id, case.question, payload.retrieval_limit
            )
            chunk_ids = {str(item.chunk_id) for item in response.retrieved_chunks}
            valid_citations = sum(
                str(citation.chunk_id) in chunk_ids for citation in response.citations
            )
            evidence_score = (
                _percentage(valid_citations, len(response.citations))
                if response.citations
                else 0.0
            )
            return (
                response.answer,
                [item.source_path for item in response.retrieved_chunks],
                evidence_score,
                response.usage.total_tokens,
                response.duration_ms,
            )

        if payload.mode == "single_agent":
            response = diagnosis_service.diagnose(
                session, project_id, case.question, payload.max_iterations
            )
            paths, evidence_score = _tool_evidence(response.tool_calls)
            return (
                response.answer,
                paths,
                evidence_score,
                response.usage.total_tokens,
                response.duration_ms,
            )

        response = multi_agent_diagnosis_service.diagnose(
            session, project_id, case.question, payload.max_iterations
        )
        paths, _ = _tool_evidence(response.tool_calls)
        # 多 Agent 的审查 Agent 已专门判断证据忠实度，直接使用它给出的审查分。
        return (
            response.final_answer,
            paths,
            float(response.review.score),
            response.usage.total_tokens,
            response.duration_ms,
        )

    @staticmethod
    def _score_result(
        case: EvaluationCase,
        answer: str,
        retrieved_files: list[str],
        evidence_score: float,
        mode: str,
    ) -> tuple[float, float, float, bool]:
        matched_files = sum(
            any(_file_matches(expected, actual) for actual in retrieved_files)
            for expected in case.expected_files
        )
        retrieval_score = _percentage(matched_files, len(case.expected_files))
        normalized_answer = answer.casefold()
        matched_keywords = sum(
            keyword.casefold() in normalized_answer for keyword in case.required_keywords
        )
        keyword_score = _percentage(matched_keywords, len(case.required_keywords))
        if mode == "retrieval":
            # 纯检索没有生成答案，只考察目标文件是否被召回。
            overall_score = retrieval_score
        else:
            overall_score = round(
                retrieval_score * 0.45 + keyword_score * 0.30 + evidence_score * 0.25,
                2,
            )
        return retrieval_score, keyword_score, overall_score, overall_score >= 70

    def run(
        self, session: Session, project_id: str, payload: EvaluationRunCreate
    ) -> EvaluationRunDetail:
        cases = self._selected_cases(
            session, project_id, [str(case_id) for case_id in payload.case_ids]
        )
        if not cases:
            raise ValueError("No evaluation cases selected")

        run = EvaluationRun(
            project_id=project_id,
            name=payload.name,
            mode=payload.mode,
            status="running",
            chat_model=settings.chat_model_name,
            embedding_model=settings.embedding_model_name,
            chunk_strategies=self._chunk_strategies(session, project_id),
            case_count=len(cases),
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        started = perf_counter()
        results: list[EvaluationResult] = []

        for case in cases:
            case_started = perf_counter()
            try:
                answer, files, evidence_score, tokens, duration_ms = self._execute_case(
                    session, project_id, case, payload
                )
                retrieval, keyword, overall, passed = self._score_result(
                    case, answer, files, evidence_score, payload.mode
                )
                result = EvaluationResult(
                    run_id=run.id,
                    case_id=case.id,
                    case_name=case.name,
                    question=case.question,
                    expected_files=case.expected_files,
                    required_keywords=case.required_keywords,
                    answer=answer,
                    retrieved_files=list(dict.fromkeys(files)),
                    retrieval_score=retrieval,
                    keyword_score=keyword,
                    evidence_score=evidence_score,
                    overall_score=overall,
                    passed=passed,
                    total_tokens=tokens,
                    duration_ms=duration_ms,
                )
            except Exception as error:
                # 单题失败不终止整批实验，便于看到模型偶发失败率。
                session.rollback()
                result = EvaluationResult(
                    run_id=run.id,
                    case_id=case.id,
                    case_name=case.name,
                    question=case.question,
                    expected_files=case.expected_files,
                    required_keywords=case.required_keywords,
                    answer="",
                    retrieved_files=[],
                    error_message=f"{type(error).__name__}: {str(error)}"[:1000],
                    duration_ms=int((perf_counter() - case_started) * 1000),
                )
            session.add(result)
            session.commit()
            session.refresh(result)
            results.append(result)

        successful = [result for result in results if result.error_message is None]
        divisor = len(successful) or 1
        run.status = "completed" if len(successful) == len(results) else "completed_with_errors"
        run.passed_count = sum(result.passed for result in results)
        run.average_retrieval_score = round(
            sum(result.retrieval_score for result in successful) / divisor, 2
        )
        run.average_keyword_score = round(
            sum(result.keyword_score for result in successful) / divisor, 2
        )
        run.average_evidence_score = round(
            sum(result.evidence_score for result in successful) / divisor, 2
        )
        run.average_overall_score = round(
            sum(result.overall_score for result in successful) / divisor, 2
        )
        run.total_tokens = sum(result.total_tokens for result in results)
        run.duration_ms = int((perf_counter() - started) * 1000)
        run.completed_at = datetime.now(UTC)
        session.commit()
        session.refresh(run)
        return EvaluationRunDetail.model_validate(
            {**EvaluationRunSummary.model_validate(run).model_dump(), "results": results}
        )

    @staticmethod
    def list_runs(session: Session, project_id: str) -> list[EvaluationRunSummary]:
        rows = session.scalars(
            select(EvaluationRun)
            .where(EvaluationRun.project_id == project_id)
            .order_by(EvaluationRun.created_at.desc())
        ).all()
        return [EvaluationRunSummary.model_validate(row) for row in rows]

    @staticmethod
    def get_run(
        session: Session, project_id: str, run_id: str
    ) -> EvaluationRunDetail | None:
        run = session.scalar(
            select(EvaluationRun).where(
                EvaluationRun.id == run_id, EvaluationRun.project_id == project_id
            )
        )
        if run is None:
            return None
        results = session.scalars(
            select(EvaluationResult)
            .where(EvaluationResult.run_id == run.id)
            .order_by(EvaluationResult.created_at)
        ).all()
        return EvaluationRunDetail.model_validate(
            {**EvaluationRunSummary.model_validate(run).model_dump(), "results": results}
        )


evaluation_service = EvaluationService()
