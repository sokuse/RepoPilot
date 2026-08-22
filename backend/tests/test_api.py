from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from repopilot.db.base import Base
from repopilot.db.session import get_session
from repopilot.main import app
from repopilot.models.project import Project
from repopilot.models.repository_file import RepositoryFile

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
