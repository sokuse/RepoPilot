import json
from uuid import uuid4

from repopilot.schemas.diagnosis import ToolCallTrace
from repopilot.services.diagnosis_service import (
    AgentDecision,
    DiagnosisService,
    RequestedToolCall,
)
from repopilot.services.repository_tool_service import ToolExecution


class FakeToolCallingProvider:
    def __init__(self) -> None:
        self.calls = 0

    def decide(self, messages, *, allow_tools: bool, force_tool: bool) -> AgentDecision:
        self.calls += 1
        if self.calls == 1:
            assert allow_tools is True
            assert force_tool is True
            return AgentDecision(
                assistant_message={
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "semantic_search",
                                "arguments": '{"query":"错误传递"}',
                            },
                        }
                    ],
                },
                content="",
                tool_calls=[
                    RequestedToolCall(
                        call_id="call-1",
                        name="semantic_search",
                        arguments={"query": "错误传递"},
                    )
                ],
            )

        assert messages[-1]["role"] == "tool"
        assert force_tool is False
        return AgentDecision(
            assistant_message={"role": "assistant", "content": "错误通过 SSE 事件传递。"},
            content="错误通过 SSE 事件传递。",
            tool_calls=[],
        )


def test_diagnosis_graph_calls_tool_then_generates_answer(monkeypatch) -> None:
    provider = FakeToolCallingProvider()
    monkeypatch.setattr(
        "repopilot.services.diagnosis_service.get_tool_calling_provider",
        lambda: provider,
    )

    def fake_execute(*_args) -> ToolExecution:
        result = json.dumps({"results": [{"source_path": "api/routes/rag.py"}]})
        return ToolExecution(
            trace=ToolCallTrace(
                call_id="call-1",
                name="semantic_search",
                arguments={"query": "错误传递"},
                summary="语义检索返回 1 个相关切片",
                result=result,
                success=True,
                duration_ms=3,
            ),
            model_content=result,
        )

    monkeypatch.setattr(
        "repopilot.services.diagnosis_service.repository_tool_service.execute",
        fake_execute,
    )

    response = DiagnosisService.diagnose(
        None,
        str(uuid4()),
        "流式错误如何传递？",
        4,
    )

    assert response.answer == "错误通过 SSE 事件传递。"
    assert response.iterations == 2
    assert response.tool_calls[0].name == "semantic_search"
    assert response.warnings == []
