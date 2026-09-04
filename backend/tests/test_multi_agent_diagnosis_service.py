import json
from uuid import uuid4

import httpx
from openai import APIConnectionError

from repopilot.schemas.diagnosis import DiagnosisResponse, ToolCallTrace
from repopilot.schemas.rag import RagTokenUsage
from repopilot.services.multi_agent_diagnosis_service import (
    MultiAgentDiagnosisService,
    TextAgentResult,
)


class FakeTextAgentProvider:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, _system: str, user: str, *, json_mode: bool) -> TextAgentResult:
        self.calls += 1
        if self.calls == 1:
            assert json_mode is False
            assert "路由如何注册" in user
            return TextAgentResult(
                content="1. 搜索 include_router。\n2. 读取入口文件。",
                usage=RagTokenUsage(prompt_tokens=8, completion_tokens=2, total_tokens=10),
            )

        assert json_mode is True
        assert "api/router.py" in user
        return TextAgentResult(
            content=json.dumps(
                {
                    "passed": True,
                    "score": 92,
                    "issues": [],
                    "final_answer": "路由在 api/router.py 中通过 include_router 注册。",
                },
                ensure_ascii=False,
            ),
            usage=RagTokenUsage(prompt_tokens=16, completion_tokens=4, total_tokens=20),
        )


def test_multi_agent_graph_plans_investigates_and_reviews(monkeypatch) -> None:
    provider = FakeTextAgentProvider()
    monkeypatch.setattr(
        "repopilot.services.multi_agent_diagnosis_service.get_text_agent_provider",
        lambda: provider,
    )
    tool_trace = ToolCallTrace(
        call_id="call-1",
        name="semantic_search",
        arguments={"query": "include_router"},
        summary="语义检索返回 1 个相关切片",
        result='{"source_path":"api/router.py"}',
        success=True,
        duration_ms=2,
    )
    monkeypatch.setattr(
        "repopilot.services.multi_agent_diagnosis_service.diagnosis_service.diagnose",
        lambda _session, project_id, question, _iterations: DiagnosisResponse(
            project_id=project_id,
            question=question,
            answer="草稿：api/router.py 使用 include_router。",
            model="qwen-test",
            iterations=2,
            duration_ms=30,
            usage=RagTokenUsage(prompt_tokens=24, completion_tokens=6, total_tokens=30),
            tool_calls=[tool_trace],
            warnings=[],
        ),
    )

    response = MultiAgentDiagnosisService.diagnose(
        None,
        str(uuid4()),
        "路由如何注册？",
        3,
    )

    assert [agent.name for agent in response.agents] == [
        "planner",
        "investigator",
        "reviewer",
    ]
    assert response.review.passed is True
    assert response.review.score == 92
    assert response.final_answer.startswith("路由在 api/router.py")
    assert response.usage.total_tokens == 60
    assert response.tool_calls[0].name == "semantic_search"


def test_invalid_reviewer_json_falls_back_to_investigator_draft(monkeypatch) -> None:
    class InvalidReviewProvider:
        def generate(self, _system: str, _user: str, *, json_mode: bool) -> TextAgentResult:
            if json_mode:
                return TextAgentResult(content="not-json", usage=RagTokenUsage())
            return TextAgentResult(content="1. 搜索代码。\n2. 核对证据。", usage=RagTokenUsage())

    monkeypatch.setattr(
        "repopilot.services.multi_agent_diagnosis_service.get_text_agent_provider",
        lambda: InvalidReviewProvider(),
    )
    monkeypatch.setattr(
        "repopilot.services.multi_agent_diagnosis_service.diagnosis_service.diagnose",
        lambda _session, project_id, question, _iterations: DiagnosisResponse(
            project_id=project_id,
            question=question,
            answer="可保留的调查草稿。",
            model="qwen-test",
            iterations=2,
            duration_ms=10,
            usage=RagTokenUsage(),
            tool_calls=[],
            warnings=[],
        ),
    )

    response = MultiAgentDiagnosisService.diagnose(None, str(uuid4()), "测试问题", 3)

    assert response.review.passed is False
    assert response.final_answer == "可保留的调查草稿。"
    assert "审查结果解析失败" in response.warnings[0]


def test_planner_api_failure_uses_default_plan(monkeypatch) -> None:
    class PlannerFailureProvider:
        def __init__(self) -> None:
            self.calls = 0

        def generate(self, _system: str, _user: str, *, json_mode: bool) -> TextAgentResult:
            self.calls += 1
            if self.calls == 1:
                raise APIConnectionError(request=httpx.Request("POST", "https://example.com"))
            assert json_mode is True
            return TextAgentResult(
                content=json.dumps(
                    {
                        "passed": True,
                        "score": 80,
                        "issues": [],
                        "final_answer": "调查结果。",
                    },
                    ensure_ascii=False,
                ),
                usage=RagTokenUsage(),
            )

    provider = PlannerFailureProvider()
    monkeypatch.setattr(
        "repopilot.services.multi_agent_diagnosis_service.get_text_agent_provider",
        lambda: provider,
    )
    monkeypatch.setattr(
        "repopilot.services.multi_agent_diagnosis_service.diagnosis_service.diagnose",
        lambda _session, project_id, question, _iterations: DiagnosisResponse(
            project_id=project_id,
            question=question,
            answer="调查结果。",
            model="qwen-test",
            iterations=2,
            duration_ms=10,
            usage=RagTokenUsage(),
            tool_calls=[],
            warnings=[],
        ),
    )

    response = MultiAgentDiagnosisService.diagnose(None, str(uuid4()), "测试问题", 3)

    assert response.final_answer == "调查结果。"
    assert response.agents[0].output.startswith("1. 使用语义检索")
    assert "默认调查计划" in response.warnings[0]


def test_reviewer_api_failure_returns_investigator_draft(monkeypatch) -> None:
    class ReviewerFailureProvider:
        def generate(self, _system: str, _user: str, *, json_mode: bool) -> TextAgentResult:
            if json_mode:
                raise APIConnectionError(request=httpx.Request("POST", "https://example.com"))
            return TextAgentResult(content="调查计划。", usage=RagTokenUsage())

    monkeypatch.setattr(
        "repopilot.services.multi_agent_diagnosis_service.get_text_agent_provider",
        lambda: ReviewerFailureProvider(),
    )
    monkeypatch.setattr(
        "repopilot.services.multi_agent_diagnosis_service.diagnosis_service.diagnose",
        lambda _session, project_id, question, _iterations: DiagnosisResponse(
            project_id=project_id,
            question=question,
            answer="有工具证据的调查草稿。",
            model="qwen-test",
            iterations=2,
            duration_ms=10,
            usage=RagTokenUsage(),
            tool_calls=[],
            warnings=[],
        ),
    )

    response = MultiAgentDiagnosisService.diagnose(None, str(uuid4()), "测试问题", 3)

    assert response.review.passed is False
    assert response.final_answer == "有工具证据的调查草稿。"
    assert "审查 Agent 暂时不可用" in response.warnings[0]
