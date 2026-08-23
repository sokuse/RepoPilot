from uuid import uuid4

from repopilot.schemas.retrieval import SemanticSearchResponse, SemanticSearchResult
from repopilot.services.rag_service import RagService


class FakeChatProvider:
    def __init__(self, answer: str) -> None:
        self.answer_text = answer

    def answer(self, _question: str, context: str) -> str:
        assert "[S1]" in context
        assert "src/app.py" in context
        return self.answer_text

    def stream_answer(self, _question: str, context: str):
        assert "[S1]" in context
        assert "src/app.py" in context
        midpoint = len(self.answer_text) // 2
        yield self.answer_text[:midpoint]
        yield self.answer_text[midpoint:]


def fake_search(_session, project_id, query, _limit, _threshold):
    return SemanticSearchResponse(
        project_id=project_id,
        query=query,
        results=[
            SemanticSearchResult(
                chunk_id=uuid4(),
                score=0.88,
                source_path="src/app.py",
                start_line=10,
                end_line=18,
                symbol_name="create_app",
                strategy="python_ast",
                content="def create_app():\n    return FastAPI()",
            )
        ],
    )


def test_rag_graph_generates_and_validates_citations(monkeypatch) -> None:
    monkeypatch.setattr(
        "repopilot.services.rag_service.vector_search_service.search",
        fake_search,
    )
    monkeypatch.setattr(
        "repopilot.services.rag_service.get_chat_provider",
        lambda: FakeChatProvider("应用由 create_app 创建。[S1] 无效来源不会被采用。[S99]"),
    )

    response = RagService.ask(None, str(uuid4()), "应用在哪里创建？", 8)

    assert response.answer.startswith("应用由 create_app 创建")
    assert [citation.source_id for citation in response.citations] == ["S1"]
    assert response.citations[0].source_path == "src/app.py"
    assert [step.name for step in response.steps] == ["retrieve", "generate", "validate"]
    assert response.warnings == []


def test_rag_graph_warns_when_answer_has_no_valid_citation(monkeypatch) -> None:
    monkeypatch.setattr(
        "repopilot.services.rag_service.vector_search_service.search",
        fake_search,
    )
    monkeypatch.setattr(
        "repopilot.services.rag_service.get_chat_provider",
        lambda: FakeChatProvider("当前资料不足，无法确认。"),
    )

    response = RagService.ask(None, str(uuid4()), "未知功能在哪里？", 8)

    assert response.citations == []
    assert len(response.warnings) == 1


def test_rag_graph_streams_tokens_and_final_validated_response(monkeypatch) -> None:
    monkeypatch.setattr(
        "repopilot.services.rag_service.vector_search_service.search",
        fake_search,
    )
    monkeypatch.setattr(
        "repopilot.services.rag_service.get_chat_provider",
        lambda: FakeChatProvider("应用由 create_app 创建。[S1]"),
    )

    events = list(RagService.stream(None, str(uuid4()), "应用在哪里创建？", 8))

    assert [event["type"] for event in events] == [
        "retrieval",
        "token",
        "token",
        "step",
        "complete",
    ]
    assert "".join(event["delta"] for event in events if event["type"] == "token").endswith(
        "[S1]"
    )
    final_response = events[-1]["response"]
    assert final_response["citations"][0]["source_path"] == "src/app.py"
    assert [step["name"] for step in final_response["steps"]] == [
        "retrieve",
        "generate",
        "validate",
    ]
