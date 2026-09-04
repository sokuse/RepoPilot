import json
from types import SimpleNamespace
from uuid import uuid4

from repopilot.schemas.diagnosis import ToolCallTrace
from repopilot.services.diagnosis_service import (
    AgentDecision,
    DiagnosisService,
    QwenToolCallingProvider,
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


def test_final_answer_omits_tools_and_retries_empty_content() -> None:
    requests = []
    responses = [
        SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=None))],
            usage=SimpleNamespace(prompt_tokens=20, completion_tokens=0, total_tokens=20),
        ),
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="【诊断结论】\n问题已定位。", tool_calls=None)
                )
            ],
            usage=SimpleNamespace(prompt_tokens=22, completion_tokens=8, total_tokens=30),
        ),
    ]

    def create(**request):
        requests.append(request)
        return responses[len(requests) - 1]

    provider = object.__new__(QwenToolCallingProvider)
    provider.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )

    decision = provider.decide(
        [{"role": "user", "content": "为什么失败？"}],
        allow_tools=False,
        force_tool=False,
    )

    assert len(requests) == 2
    assert all("tools" not in request for request in requests)
    assert all("tool_choice" not in request for request in requests)
    assert "工具调查已经结束" in requests[0]["messages"][-1]["content"]
    assert decision.content.startswith("【诊断结论】")
    assert decision.usage.total_tokens == 50


def test_tool_round_disables_thinking_when_tool_call_is_required() -> None:
    requests = []
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id="call-1",
                            function=SimpleNamespace(
                                name="semantic_search",
                                arguments='{"query":"路由注册"}',
                            ),
                        )
                    ],
                )
            )
        ],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )

    def create(**request):
        requests.append(request)
        return response

    provider = object.__new__(QwenToolCallingProvider)
    provider.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )

    decision = provider.decide(
        [{"role": "user", "content": "FastAPI 路由在哪里注册？"}],
        allow_tools=True,
        force_tool=True,
    )

    assert requests[0]["tool_choice"] == "required"
    assert requests[0]["extra_body"] == {"enable_thinking": False}
    assert decision.tool_calls[0].name == "semantic_search"


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


def test_diagnosis_graph_streams_decisions_tools_and_final_response(monkeypatch) -> None:
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

    events = list(DiagnosisService.stream(None, str(uuid4()), "流式错误如何传递？", 4))

    assert [event["type"] for event in events] == [
        "start",
        "decision",
        "tool_start",
        "tool_complete",
        "complete",
    ]
    assert events[1]["tool_calls"][0]["name"] == "semantic_search"
    assert events[3]["trace"]["success"] is True
    assert events[-1]["response"]["answer"] == "错误通过 SSE 事件传递。"
