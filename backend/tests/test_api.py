from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from repopilot.db.base import Base
from repopilot.db.session import get_session
from repopilot.main import app
from repopilot.models.knowledge_chunk import KnowledgeChunk
from repopilot.models.project import Project
from repopilot.models.rag_run import RagRun
from repopilot.models.repository_file import RepositoryFile
from repopilot.models.vector_index_state import VectorIndexState
from repopilot.schemas.diagnosis import DiagnosisResponse, ToolCallTrace
from repopilot.schemas.rag import RagAnswerResponse, RagExecutionStep, RagTokenUsage
from repopilot.schemas.retrieval import SemanticSearchResult
from repopilot.services.rag_run_service import rag_run_service

test_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)
Base.metadata.create_all(bind=test_engine)


def override_get_session() -> Generator[Session, None, None]:
    with TestingSessionLocal() as session:
        yield session


app.dependency_overrides[get_session] = override_get_session
client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_database() -> Generator[None, None, None]:
    with TestingSessionLocal() as session:
        session.execute(delete(RagRun))
        session.execute(delete(VectorIndexState))
        session.execute(delete(KnowledgeChunk))
        session.execute(delete(RepositoryFile))
        session.execute(delete(Project))
        session.commit()
    yield


def create_project() -> dict[str, str]:
    response = client.post(
        "/api/v1/projects",
        json={
            "name": "LangGraph",
            "repository_url": "https://github.com/langchain-ai/langgraph",
            "default_branch": "main",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_health_check() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_create_and_list_project() -> None:
    created = create_project()

    assert created["status"] == "pending"
    assert created["repository_url"] == "https://github.com/langchain-ai/langgraph"

    list_response = client.get("/api/v1/projects")
    assert list_response.status_code == 200
    assert [project["id"] for project in list_response.json()] == [created["id"]]


def test_duplicate_repository_is_rejected() -> None:
    create_project()

    duplicate_response = client.post(
        "/api/v1/projects",
        json={
            "name": "Duplicate",
            "repository_url": "https://github.com/langchain-ai/langgraph.git",
            "default_branch": "main",
        },
    )

    assert duplicate_response.status_code == 409


def test_get_and_delete_project() -> None:
    created = create_project()

    get_response = client.get(f"/api/v1/projects/{created['id']}")
    assert get_response.status_code == 200
    assert get_response.json()["name"] == "LangGraph"

    delete_response = client.delete(f"/api/v1/projects/{created['id']}")
    assert delete_response.status_code == 204
    assert client.get(f"/api/v1/projects/{created['id']}").status_code == 404


def test_start_repository_ingestion(monkeypatch: pytest.MonkeyPatch) -> None:
    created = create_project()
    # API 测试只验证任务调度和状态变化，不访问真实 GitHub 网络。
    monkeypatch.setattr(
        "repopilot.api.routes.projects.run_repository_ingestion",
        lambda _project_id: None,
    )

    response = client.post(f"/api/v1/projects/{created['id']}/ingest")

    assert response.status_code == 202
    assert response.json()["status"] == "indexing"

    second_response = client.post(f"/api/v1/projects/{created['id']}/ingest")
    assert second_response.status_code == 409


def test_rejects_non_github_repository() -> None:
    response = client.post(
        "/api/v1/projects",
        json={
            "name": "Unsafe URL",
            "repository_url": "https://example.com/owner/repository",
            "default_branch": "main",
        },
    )

    assert response.status_code == 422


def test_build_and_list_traceable_chunks(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = create_project()
    project_id = created["id"]
    repository_root = tmp_path / project_id
    repository_root.mkdir()
    source = repository_root / "example.py"
    source.write_text(
        "import os\n\n\ndef greet(name: str) -> str:\n    return f'Hello {name}'\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "repopilot.services.chunking_service.settings.repository_storage_path",
        tmp_path,
    )

    with TestingSessionLocal() as session:
        project = session.get(Project, project_id)
        assert project is not None
        project.status = "ready"
        session.add(
            RepositoryFile(
                project_id=project_id,
                path="example.py",
                extension=".py",
                language="Python",
                size_bytes=source.stat().st_size,
                content_sha256="test-sha256",
            )
        )
        session.commit()

    first_build = client.post(f"/api/v1/projects/{project_id}/chunks")
    assert first_build.status_code == 200
    assert first_build.json()["total_chunks"] == 2

    chunks = client.get(f"/api/v1/projects/{project_id}/chunks").json()
    assert [chunk["strategy"] for chunk in chunks] == ["python_module", "python_ast"]
    assert chunks[1]["symbol_name"] == "greet"
    assert chunks[1]["start_line"] == 4

    # 重建应覆盖派生数据，而不是在每次点击后重复追加。
    second_build = client.post(f"/api/v1/projects/{project_id}/chunks")
    assert second_build.json()["total_chunks"] == 2


def test_vector_index_stats_require_ready_project() -> None:
    created = create_project()

    pending_response = client.get(f"/api/v1/projects/{created['id']}/index/stats")
    assert pending_response.status_code == 409

    with TestingSessionLocal() as session:
        project = session.get(Project, created["id"])
        assert project is not None
        project.status = "ready"
        session.commit()

    ready_response = client.get(f"/api/v1/projects/{created['id']}/index/stats")
    assert ready_response.status_code == 200
    assert ready_response.json()["ready"] is False


def test_rag_stream_returns_sse_events(monkeypatch: pytest.MonkeyPatch) -> None:
    created = create_project()
    with TestingSessionLocal() as session:
        project = session.get(Project, created["id"])
        assert project is not None
        project.status = "ready"
        session.commit()

    monkeypatch.setattr(
        "repopilot.api.routes.rag.rag_service.stream",
        lambda *_args: iter(
            [
                {"type": "token", "delta": "流式"},
                {"type": "token", "delta": "回答"},
            ]
        ),
    )

    response = client.post(
        f"/api/v1/projects/{created['id']}/rag/stream",
        json={"question": "应用在哪里创建？", "retrieval_limit": 8},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert 'data: {"type":"token","delta":"流式"}' in response.text
    assert 'data: {"type":"token","delta":"回答"}' in response.text


def test_list_and_get_rag_run_history() -> None:
    created = create_project()
    with TestingSessionLocal() as session:
        project = session.get(Project, created["id"])
        assert project is not None
        project.status = "ready"
        session.commit()
        run = rag_run_service.start(session, created["id"], "应用在哪里创建？", 8)
        chunk = SemanticSearchResult(
            chunk_id=uuid4(),
            score=0.88,
            source_path="src/app.py",
            start_line=10,
            end_line=18,
            symbol_name="create_app",
            strategy="python_ast",
            content="def create_app(): ...",
        )
        rag_run_service.complete(
            session,
            run.id,
            RagAnswerResponse(
                run_id=run.id,
                project_id=created["id"],
                question="应用在哪里创建？",
                answer="应用在工厂函数中创建。[S1]",
                citations=[],
                retrieved_chunks=[chunk],
                steps=[RagExecutionStep(name="retrieve", label="语义召回", detail="1 个")],
                warnings=[],
                usage=RagTokenUsage(
                    prompt_tokens=40,
                    completion_tokens=12,
                    total_tokens=52,
                ),
                duration_ms=850,
            ),
        )
        run_id = run.id

    list_response = client.get(f"/api/v1/projects/{created['id']}/rag/runs")
    assert list_response.status_code == 200
    assert list_response.json()[0]["total_tokens"] == 52

    detail_response = client.get(
        f"/api/v1/projects/{created['id']}/rag/runs/{run_id}"
    )
    assert detail_response.status_code == 200
    assert detail_response.json()["answer"].startswith("应用在工厂函数中创建")
    assert detail_response.json()["retrieved_chunks"][0]["source_path"] == "src/app.py"


def test_repository_diagnosis_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    created = create_project()
    with TestingSessionLocal() as session:
        project = session.get(Project, created["id"])
        assert project is not None
        project.status = "ready"
        session.commit()

    monkeypatch.setattr(
        "repopilot.api.routes.diagnosis.diagnosis_service.diagnose",
        lambda _session, project_id, question, _max_iterations: DiagnosisResponse(
            project_id=project_id,
            question=question,
            answer="错误通过 SSE error 事件传递。",
            model="qwen-test",
            iterations=2,
            duration_ms=120,
            usage=RagTokenUsage(prompt_tokens=30, completion_tokens=8, total_tokens=38),
            tool_calls=[
                ToolCallTrace(
                    call_id="call-1",
                    name="semantic_search",
                    arguments={"query": "错误传递"},
                    summary="语义检索返回 1 个相关切片",
                    result='{"count": 1}',
                    success=True,
                    duration_ms=3,
                )
            ],
            warnings=[],
        ),
    )

    response = client.post(
        f"/api/v1/projects/{created['id']}/diagnosis",
        json={"question": "流式错误如何传递？", "max_iterations": 4},
    )

    assert response.status_code == 200
    assert response.json()["tool_calls"][0]["name"] == "semantic_search"
    assert response.json()["iterations"] == 2
