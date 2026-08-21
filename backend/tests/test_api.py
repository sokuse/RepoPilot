from fastapi.testclient import TestClient

from repopilot.main import app

client = TestClient(app)


def test_health_check() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_create_and_list_project() -> None:
    create_response = client.post(
        "/api/v1/projects",
        json={
            "name": "LangGraph",
            "repository_url": "https://github.com/langchain-ai/langgraph",
            "default_branch": "main",
        },
    )

    assert create_response.status_code == 201
    assert create_response.json()["status"] == "pending"

    list_response = client.get("/api/v1/projects")
    assert list_response.status_code == 200
    assert any(project["name"] == "LangGraph" for project in list_response.json())

