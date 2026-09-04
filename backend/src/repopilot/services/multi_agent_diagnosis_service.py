import json
import re
from dataclasses import dataclass
from functools import lru_cache
from time import perf_counter
from typing import Protocol, TypedDict

from langgraph.graph import END, START, StateGraph
from openai import OpenAI
from pydantic import ValidationError
from sqlalchemy.orm import Session

from repopilot.core.config import settings
from repopilot.schemas.diagnosis import (
    AgentExecutionStep,
    DiagnosisReview,
    MultiAgentDiagnosisResponse,
    ToolCallTrace,
)
from repopilot.schemas.rag import RagTokenUsage
from repopilot.services.diagnosis_service import diagnosis_service
from repopilot.services.rag_service import ChatConfigurationError

MAX_REVIEW_TOOL_RESULT_CHARS = 4_000
JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


@dataclass(frozen=True)
class TextAgentResult:
    content: str
    usage: RagTokenUsage


class TextAgentProvider(Protocol):
    def generate(self, system_prompt: str, user_prompt: str, *, json_mode: bool) -> TextAgentResult:
        ...


class QwenTextAgentProvider:
    def __init__(self) -> None:
        if not settings.qwen_api_key:
            raise ChatConfigurationError
        self.client = OpenAI(
            api_key=settings.qwen_api_key,
            base_url=settings.embedding_api_base_url,
        )

    def generate(self, system_prompt: str, user_prompt: str, *, json_mode: bool) -> TextAgentResult:
        request: dict[str, object] = {
            "model": settings.chat_model_name,
            "temperature": settings.rag_temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if json_mode:
            request["response_format"] = {"type": "json_object"}
        response = self.client.chat.completions.create(**request)  # type: ignore[arg-type]
        content = (response.choices[0].message.content or "").strip()
        return TextAgentResult(
            content=content,
            usage=RagTokenUsage(
                prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
                completion_tokens=response.usage.completion_tokens if response.usage else 0,
                total_tokens=response.usage.total_tokens if response.usage else 0,
            ),
        )


@lru_cache
def get_text_agent_provider() -> TextAgentProvider:
    return QwenTextAgentProvider()


class MultiAgentState(TypedDict, total=False):
    session: Session
    project_id: str
    question: str
    max_iterations: int
    plan: str
    draft_answer: str
    tool_calls: list[ToolCallTrace]
    review: DiagnosisReview
    agents: list[AgentExecutionStep]
    usage: RagTokenUsage
    warnings: list[str]


PLANNER_PROMPT = """你是 RepoPilot 的规划 Agent。你的任务不是回答问题，而是为调查当前代码仓库
制定一个简洁、可执行的计划。计划最多五步，应说明要搜索的关键词、可能需要读取的文件类型，
以及最终需要验证的调用链。不要假设任何尚未通过工具取得的仓库事实。使用中文 Markdown。"""

REVIEWER_PROMPT = """你是 RepoPilot 的证据审查 Agent。请对调查 Agent 的草稿进行严格审查：
1. 每个核心结论是否能被工具证据支持；2. 文件路径和行号是否来自证据；3. 是否存在夸大或猜测；
4. 回答是否真正解决用户问题。你必须返回一个 JSON 对象，且只能包含 passed、score、issues、
final_answer 四个字段。score 为 0 到 100 的整数；issues 为中文字符串数组；final_answer 必须是经过
修订、可直接展示给用户的中文答案。证据不足时要明确说明，不能补造事实。"""


def _add_usage(left: RagTokenUsage, right: RagTokenUsage) -> RagTokenUsage:
    return RagTokenUsage(
        prompt_tokens=left.prompt_tokens + right.prompt_tokens,
        completion_tokens=left.completion_tokens + right.completion_tokens,
        total_tokens=left.total_tokens + right.total_tokens,
    )


def planner_node(state: MultiAgentState) -> dict[str, object]:
    started = perf_counter()
    result = get_text_agent_provider().generate(
        PLANNER_PROMPT,
        f"需要调查的问题：\n{state['question']}",
        json_mode=False,
    )
    plan = result.content or "1. 使用语义检索定位相关实现。\n2. 阅读关键文件并核对调用链。"
    step = AgentExecutionStep(
        name="planner",
        label="规划 Agent",
        output=plan,
        duration_ms=int((perf_counter() - started) * 1000),
        usage=result.usage,
    )
    return {
        "plan": plan,
        "agents": [step],
        "usage": _add_usage(state.get("usage", RagTokenUsage()), result.usage),
    }


def investigator_node(state: MultiAgentState) -> dict[str, object]:
    started = perf_counter()
    investigation_prompt = (
        f"原始问题：\n{state['question']}\n\n规划 Agent 给出的调查计划：\n{state['plan']}\n\n"
        "请按照计划使用仓库工具调查，并给出带文件路径和行号的草稿答案。"
    )
    result = diagnosis_service.diagnose(
        state["session"],
        state["project_id"],
        investigation_prompt,
        state["max_iterations"],
    )
    step = AgentExecutionStep(
        name="investigator",
        label="调查 Agent",
        output=result.answer,
        duration_ms=int((perf_counter() - started) * 1000),
        usage=result.usage,
    )
    return {
        "draft_answer": result.answer,
        "tool_calls": result.tool_calls,
        "agents": [*state.get("agents", []), step],
        "usage": _add_usage(state.get("usage", RagTokenUsage()), result.usage),
        "warnings": [*state.get("warnings", []), *result.warnings],
    }


def _review_evidence(tool_calls: list[ToolCallTrace]) -> str:
    evidence = [
        {
            "tool": call.name,
            "arguments": call.arguments,
            "summary": call.summary,
            "success": call.success,
            "result": call.result[:MAX_REVIEW_TOOL_RESULT_CHARS],
        }
        for call in tool_calls
    ]
    return json.dumps(evidence, ensure_ascii=False)


def _parse_review(content: str, draft_answer: str) -> tuple[DiagnosisReview, str | None]:
    try:
        cleaned = JSON_FENCE.sub("", content.strip())
        return DiagnosisReview.model_validate_json(cleaned), None
    except (ValidationError, ValueError, json.JSONDecodeError):
        fallback = DiagnosisReview(
            passed=False,
            score=0,
            issues=["审查 Agent 未返回合法 JSON，已保留调查 Agent 的草稿。"],
            final_answer=draft_answer,
        )
        return fallback, "审查结果解析失败，本次最终答案使用调查草稿。"


def reviewer_node(state: MultiAgentState) -> dict[str, object]:
    started = perf_counter()
    prompt = (
        f"用户问题：\n{state['question']}\n\n调查计划：\n{state['plan']}\n\n"
        f"调查草稿：\n{state['draft_answer']}\n\n工具证据（JSON）：\n"
        f"{_review_evidence(state.get('tool_calls', []))}"
    )
    result = get_text_agent_provider().generate(REVIEWER_PROMPT, prompt, json_mode=True)
    review, warning = _parse_review(result.content, state["draft_answer"])
    output = f"评分：{review.score}/100；通过：{'是' if review.passed else '否'}"
    if review.issues:
        output += "\n问题：" + "；".join(review.issues)
    step = AgentExecutionStep(
        name="reviewer",
        label="审查 Agent",
        output=output,
        duration_ms=int((perf_counter() - started) * 1000),
        usage=result.usage,
    )
    warnings = list(state.get("warnings", []))
    if warning:
        warnings.append(warning)
    return {
        "review": review,
        "agents": [*state.get("agents", []), step],
        "usage": _add_usage(state.get("usage", RagTokenUsage()), result.usage),
        "warnings": warnings,
    }


def build_multi_agent_graph():
    builder = StateGraph(MultiAgentState)
    builder.add_node("planner", planner_node)
    builder.add_node("investigator", investigator_node)
    builder.add_node("reviewer", reviewer_node)
    builder.add_edge(START, "planner")
    builder.add_edge("planner", "investigator")
    builder.add_edge("investigator", "reviewer")
    builder.add_edge("reviewer", END)
    return builder.compile()


multi_agent_graph = build_multi_agent_graph()


class MultiAgentDiagnosisService:
    @staticmethod
    def diagnose(
        session: Session,
        project_id: str,
        question: str,
        max_iterations: int,
    ) -> MultiAgentDiagnosisResponse:
        started = perf_counter()
        result = multi_agent_graph.invoke(
            {
                "session": session,
                "project_id": project_id,
                "question": question,
                "max_iterations": max_iterations,
                "tool_calls": [],
                "agents": [],
                "usage": RagTokenUsage(),
                "warnings": [],
            }
        )
        review = result["review"]
        return MultiAgentDiagnosisResponse(
            project_id=project_id,
            question=question,
            model=settings.chat_model_name,
            plan=result["plan"],
            draft_answer=result["draft_answer"],
            review=review,
            final_answer=review.final_answer,
            tool_calls=result.get("tool_calls", []),
            agents=result.get("agents", []),
            usage=result.get("usage", RagTokenUsage()),
            duration_ms=int((perf_counter() - started) * 1000),
            warnings=result.get("warnings", []),
        )


multi_agent_diagnosis_service = MultiAgentDiagnosisService()
