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
from repopilot.models.conversation import Conversation, ConversationMessage, MemoryChunk
from repopilot.models.evaluation import EvaluationCase, EvaluationResult, EvaluationRun
from repopilot.models.knowledge_chunk import KnowledgeChunk
from repopilot.models.project import Project
from repopilot.models.rag_run import RagRun
from repopilot.models.repository_file import RepositoryFile
from repopilot.models.vector_index_state import VectorIndexState
from repopilot.schemas.diagnosis import (
    AgentExecutionStep,
    DiagnosisResponse,
    DiagnosisReview,
    MultiAgentDiagnosisResponse,
    ToolCallTrace,
)
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
def clean_database(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setattr(
        "repopilot.api.routes.diagnosis.memory_service.remember",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "repopilot.api.routes.conversations.memory_service.forget_conversation",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "repopilot.api.routes.conversations.memory_service.remember",
        lambda *_args, **_kwargs: [],
    )
    with TestingSessionLocal() as session:
        session.execute(delete(EvaluationResult))
        session.execute(delete(EvaluationRun))
        session.execute(delete(EvaluationCase))
        session.execute(delete(MemoryChunk))
        session.execute(delete(ConversationMessage))
        session.execute(delete(Conversation))
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


def test_create_read_feedback_and_delete_conversation() -> None:
    created = create_project()
    create_response = client.post(
        f"/api/v1/projects/{created['id']}/conversations",
        json={"title": "排查代理问题"},
    )
    assert create_response.status_code == 201
    conversation_id = create_response.json()["id"]

    with TestingSessionLocal() as session:
        message = ConversationMessage(
            conversation_id=conversation_id,
            role="assistant",
            content="请检查代理配置。",
        )
        session.add(message)
        session.commit()
        message_id = message.id

    detail = client.get(
        f"/api/v1/projects/{created['id']}/conversations/{conversation_id}"
    )
    assert detail.status_code == 200
    assert detail.json()["messages"][0]["content"] == "请检查代理配置。"

    feedback = client.put(
        f"/api/v1/projects/{created['id']}/conversations/"
        f"{conversation_id}/messages/{message_id}/feedback",
        json={"feedback": "helpful", "note": "已经解决"},
    )
    assert feedback.status_code == 200
    assert feedback.json()["feedback"] == "helpful"

    delete_response = client.delete(
        f"/api/v1/projects/{created['id']}/conversations/{conversation_id}"
    )
    assert delete_response.status_code == 204


def test_create_list_and_delete_evaluation_case() -> None:
    created = create_project()
    with TestingSessionLocal() as session:
        project = session.get(Project, created["id"])
        assert project is not None
        project.status = "ready"
        session.commit()

    create_response = client.post(
        f"/api/v1/projects/{created['id']}/evaluations/cases",
        json={
            "name": "FastAPI 入口",
            "question": "项目在哪里创建 FastAPI 应用？",
            "expected_files": ["backend/src/repopilot/main.py"],
            "required_keywords": ["FastAPI", "create_app"],
        },
    )
    assert create_response.status_code == 201
    case_id = create_response.json()["id"]

    list_response = client.get(f"/api/v1/projects/{created['id']}/evaluations/cases")
    assert list_response.status_code == 200
    assert list_response.json()[0]["required_keywords"] == ["FastAPI", "create_app"]

    delete_response = client.delete(
        f"/api/v1/projects/{created['id']}/evaluations/cases/{case_id}"
    )
    assert delete_response.status_code == 204


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
    indexed_memories = []
    monkeypatch.setattr(
        "repopilot.api.routes.diagnosis.memory_service.remember",
        lambda *args, **_kwargs: indexed_memories.append(args),
    )

    response = client.post(
        f"/api/v1/projects/{created['id']}/diagnosis",
        json={"question": "流式错误如何传递？", "max_iterations": 4},
    )

    assert response.status_code == 200
    assert response.json()["tool_calls"][0]["name"] == "semantic_search"
    assert response.json()["iterations"] == 2
    assert indexed_memories[0][2] == "diagnosis"
    assert "流式错误如何传递" in indexed_memories[0][4]


def test_multi_agent_diagnosis_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    created = create_project()
    with TestingSessionLocal() as session:
        project = session.get(Project, created["id"])
        assert project is not None
        project.status = "ready"
        session.commit()

    usage = RagTokenUsage(prompt_tokens=80, completion_tokens=20, total_tokens=100)
    monkeypatch.setattr(
        "repopilot.api.routes.diagnosis.multi_agent_diagnosis_service.diagnose",
        lambda _session, project_id, question, _max_iterations: MultiAgentDiagnosisResponse(
            project_id=project_id,
            question=question,
            model="qwen-test",
            plan="搜索路由并读取入口文件。",
            draft_answer="调查草稿。",
            review=DiagnosisReview(
                passed=True,
                score=90,
                issues=[],
                final_answer="经过审查的最终回答。",
            ),
            final_answer="经过审查的最终回答。",
            tool_calls=[],
            agents=[
                AgentExecutionStep(
                    name="planner",
                    label="规划 Agent",
                    output="搜索路由。",
                    duration_ms=20,
                    usage=usage,
                )
            ],
            usage=usage,
            duration_ms=100,
            warnings=[],
        ),
    )

    response = client.post(
        f"/api/v1/projects/{created['id']}/diagnosis/multi-agent",
        json={"question": "路由如何注册？", "max_iterations": 3},
    )

    assert response.status_code == 200
    assert response.json()["review"]["score"] == 90
    assert response.json()["final_answer"] == "经过审查的最终回答。"


def test_repository_diagnosis_stream_returns_sse_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = create_project()
    with TestingSessionLocal() as session:
        project = session.get(Project, created["id"])
        assert project is not None
        project.status = "ready"
        session.commit()

    monkeypatch.setattr(
        "repopilot.api.routes.diagnosis.diagnosis_service.stream",
        lambda *_args: iter(
            [
                {"type": "start", "question": "错误如何传递？", "max_iterations": 3},
                {
                    "type": "tool_start",
                    "call_id": "call-1",
                    "name": "semantic_search",
                    "arguments": {"query": "错误传递"},
                },
                {"type": "complete", "response": {"answer": "诊断完成"}},
            ]
        ),
    )

    response = client.post(
        f"/api/v1/projects/{created['id']}/diagnosis/stream",
        json={"question": "错误如何传递？", "max_iterations": 3},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert 'data: {"type":"tool_start"' in response.text
    assert 'data: {"type":"complete"' in response.text
