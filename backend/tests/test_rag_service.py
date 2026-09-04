from types import SimpleNamespace
from uuid import uuid4

import pytest

from repopilot.schemas.conversation import MemorySearchResult
from repopilot.schemas.rag import RagTokenUsage
from repopilot.schemas.retrieval import SemanticSearchResponse, SemanticSearchResult
from repopilot.services.rag_run_service import rag_run_service
from repopilot.services.rag_service import (
    ChatAnswer,
    ChatStreamPart,
    RagService,
    conversation_service,
    memory_service,
)


class FakeChatProvider:
    def __init__(self, answer: str) -> None:
        self.answer_text = answer

    def answer(self, _question: str, context: str) -> ChatAnswer:
        assert "[S1]" in context
        assert "src/app.py" in context
        return ChatAnswer(
            text=self.answer_text,
            usage=RagTokenUsage(prompt_tokens=40, completion_tokens=12, total_tokens=52),
        )

    def stream_answer(self, _question: str, context: str):
        assert "[S1]" in context
        assert "src/app.py" in context
        midpoint = len(self.answer_text) // 2
        yield ChatStreamPart(delta=self.answer_text[:midpoint])
        yield ChatStreamPart(delta=self.answer_text[midpoint:])
        yield ChatStreamPart(
            usage=RagTokenUsage(prompt_tokens=40, completion_tokens=12, total_tokens=52)
        )


@pytest.fixture(autouse=True)
def fake_run_tracking(monkeypatch: pytest.MonkeyPatch) -> None:
    """图单测只关心编排逻辑，运行记录持久化由独立测试覆盖。"""

    class FakeRun:
        id = str(uuid4())

    monkeypatch.setattr(rag_run_service, "start", lambda *_args: FakeRun())
    monkeypatch.setattr(rag_run_service, "complete", lambda *_args: None)
    monkeypatch.setattr(rag_run_service, "fail", lambda *_args: None)
    monkeypatch.setattr(memory_service, "search", lambda *_args: [])
    monkeypatch.setattr(memory_service, "remember", lambda *_args: [])


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
    assert response.usage.total_tokens == 52
    assert response.run_id is not None


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


def test_rag_answer_is_saved_into_conversation(monkeypatch) -> None:
    monkeypatch.setattr(
        "repopilot.services.rag_service.vector_search_service.search",
        fake_search,
    )
    class ContextAwareProvider(FakeChatProvider):
        def answer(self, question: str, context: str) -> ChatAnswer:
            assert "上一次确认使用工厂函数" in context
            assert "[M1]" in context
            assert "历史回答认为入口在 app.py" in context
            return super().answer(question, context)

    monkeypatch.setattr(
        "repopilot.services.rag_service.get_chat_provider",
        lambda: ContextAwareProvider("应用由 create_app 创建。[S1][M1]"),
    )
    saved_messages = []
    monkeypatch.setattr(
        conversation_service,
        "recent_messages",
        lambda *_args: [
            SimpleNamespace(role="assistant", content="上一次确认使用工厂函数")
        ],
    )
    monkeypatch.setattr(
        memory_service,
        "search",
        lambda *_args: [
            MemorySearchResult(
                memory_id=uuid4(),
                score=0.91,
                source_type="conversation",
                source_id=str(uuid4()),
                conversation_id=conversation_id,
                content="历史回答认为入口在 app.py",
            )
        ],
    )

    def save_message(_session, conversation_id, role, content, rag_run_id=None):
        saved_messages.append((conversation_id, role, content, rag_run_id))
        return SimpleNamespace(id=str(uuid4()))

    monkeypatch.setattr(
        conversation_service,
        "add_message",
        save_message,
    )

    conversation_id = str(uuid4())
    response = RagService.ask(
        None,
        str(uuid4()),
        "应用在哪里创建？",
        8,
        conversation_id,
    )

    assert str(response.conversation_id) == conversation_id
    assert [message[1] for message in saved_messages] == ["user", "assistant"]
    assert saved_messages[1][2].startswith("应用由 create_app")
    assert response.retrieved_memories[0].score == 0.91


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
        "run",
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
    assert final_response["usage"]["total_tokens"] == 52
    assert [step["name"] for step in final_response["steps"]] == [
        "retrieve",
        "generate",
        "validate",
    ]
