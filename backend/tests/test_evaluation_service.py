from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from repopilot.db.base import Base
from repopilot.models.evaluation import EvaluationResult, EvaluationRun
from repopilot.models.project import Project
from repopilot.models.repository_file import RepositoryFile
from repopilot.schemas.evaluation import EvaluationCaseCreate, EvaluationRunCreate
from repopilot.schemas.retrieval import SemanticSearchResponse, SemanticSearchResult
from repopilot.services.evaluation_service import evaluation_service


def test_retrieval_evaluation_calculates_and_persists_scores(monkeypatch) -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        project = Project(
            name="RepoPilot",
            repository_url="https://github.com/example/repopilot",
            status="ready",
        )
        session.add(project)
        session.flush()
        session.add(
            RepositoryFile(
                project_id=project.id,
                path="backend/src/repopilot/main.py",
                extension=".py",
                language="Python",
                size_bytes=100,
                content_sha256="evaluation-service-main-file",
            )
        )
        session.commit()
        session.refresh(project)

        case = evaluation_service.create_case(
            session,
            project.id,
            EvaluationCaseCreate(
                name="应用入口",
                question="项目在哪里创建 FastAPI 应用？",
                expected_files=["backend/src/repopilot/main.py"],
                required_keywords=["FastAPI", "create_app"],
            ),
        )

        monkeypatch.setattr(
            "repopilot.services.evaluation_service.vector_search_service.search",
            lambda *_args: SemanticSearchResponse(
                project_id=project.id,
                query=case.question,
                results=[
                    SemanticSearchResult(
                        chunk_id=uuid4(),
                        score=0.91,
                        source_path="backend/src/repopilot/main.py",
                        start_line=1,
                        end_line=20,
                        symbol_name="create_app",
                        strategy="python_ast",
                        content="def create_app(): return FastAPI()",
                    )
                ],
            ),
        )

        report = evaluation_service.run(
            session,
            project.id,
            EvaluationRunCreate(
                name="检索基线",
                mode="retrieval",
                case_ids=[case.id],
            ),
        )

        assert report.status == "completed"
        assert report.average_retrieval_score == 100
        assert report.average_overall_score == 100
        assert report.passed_count == 1
        assert session.query(EvaluationRun).count() == 1
        assert session.query(EvaluationResult).count() == 1


def test_case_validation_removes_duplicate_expectations() -> None:
    payload = EvaluationCaseCreate(
        name="路由注册",
        question="路由在哪里注册？",
        expected_files=[" api/router.py ", "api/router.py"],
        required_keywords=["include_router", "include_router"],
    )

    assert payload.expected_files == ["api/router.py"]
    assert payload.required_keywords == ["include_router"]
