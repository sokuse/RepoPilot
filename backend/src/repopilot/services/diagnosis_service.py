import json
from dataclasses import dataclass, field
from functools import lru_cache
from time import perf_counter
from typing import Any, Protocol, TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from openai import OpenAI
from sqlalchemy.orm import Session

from repopilot.core.config import settings
from repopilot.schemas.diagnosis import DiagnosisResponse, ToolCallTrace
from repopilot.schemas.rag import RagTokenUsage
from repopilot.services.rag_service import ChatConfigurationError
from repopilot.services.repository_tool_service import (
    REPOSITORY_TOOL_DEFINITIONS,
    repository_tool_service,
)

MAX_TOOL_CALLS_PER_TURN = 2
FINAL_ANSWER_ATTEMPTS = 2
FINAL_ANSWER_INSTRUCTION = """仓库工具调查已经结束。现在禁止继续申请工具，请立即根据上面的
工具结果生成最终诊断。必须使用中文，并完整包含【诊断结论】【根因分析】【代码证据】
【修复建议】【验证步骤】五个部分；如果证据不足，也要明确说明缺少什么证据。"""


class EmptyDiagnosisAnswerError(Exception):
    """模型在自动重试后仍未返回最终诊断文本。"""


@dataclass(frozen=True)
class RequestedToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class AgentDecision:
    assistant_message: dict[str, Any]
    content: str
    tool_calls: list[RequestedToolCall]
    usage: RagTokenUsage = field(default_factory=RagTokenUsage)


class ToolCallingProvider(Protocol):
    def decide(
        self,
        messages: list[dict[str, Any]],
        *,
        allow_tools: bool,
        force_tool: bool,
    ) -> AgentDecision: ...


class QwenToolCallingProvider:
    def __init__(self) -> None:
        if not settings.qwen_api_key:
            raise ChatConfigurationError
        self.client = OpenAI(
            api_key=settings.qwen_api_key,
            base_url=settings.embedding_api_base_url,
        )

    def decide(
        self,
        messages: list[dict[str, Any]],
        *,
        allow_tools: bool,
        force_tool: bool,
    ) -> AgentDecision:
        request_messages = messages
        if not allow_tools:
            request_messages = [
                *messages,
                {"role": "user", "content": FINAL_ANSWER_INSTRUCTION},
            ]

        request: dict[str, Any] = {
            "model": settings.chat_model_name,
            "temperature": settings.rag_temperature,
            "messages": request_messages,
        }
        if allow_tools:
            request["tools"] = REPOSITORY_TOOL_DEFINITIONS
            request["tool_choice"] = "required" if force_tool else "auto"

        # 最终结论轮完全不发送 tools。少数兼容接口仍可能偶发返回空 content，
        # 因此只在最终轮自动重试一次，并累计两次请求的 Token。
        attempts = 1 if allow_tools else FINAL_ANSWER_ATTEMPTS
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0
        response = None
        content = ""
        for _ in range(attempts):
            response = self.client.chat.completions.create(**request)
            if response.usage:
                prompt_tokens += response.usage.prompt_tokens
                completion_tokens += response.usage.completion_tokens
                total_tokens += response.usage.total_tokens
            content = (response.choices[0].message.content or "").strip()
            if allow_tools or content:
                break

        if response is None:  # pragma: no cover - attempts 始终至少为 1
            raise EmptyDiagnosisAnswerError
        if not allow_tools and not content:
            raise EmptyDiagnosisAnswerError

        message = response.choices[0].message
        requested_calls: list[RequestedToolCall] = []
        serialized_calls: list[dict[str, Any]] = []
        # 某些模型会在一轮同时申请大量工具；只保留前两个，控制上下文和 API 成本。
        for call in (message.tool_calls or [])[:MAX_TOOL_CALLS_PER_TURN]:
            try:
                arguments = json.loads(call.function.arguments)
                if not isinstance(arguments, dict):
                    arguments = {"_invalid_arguments": arguments}
            except json.JSONDecodeError:
                arguments = {"_invalid_json": call.function.arguments}
            requested_calls.append(
                RequestedToolCall(
                    call_id=call.id,
                    name=call.function.name,
                    arguments=arguments,
                )
            )
            serialized_calls.append(
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
            )

        assistant_message: dict[str, Any] = {"role": "assistant", "content": content or None}
        if serialized_calls:
            assistant_message["tool_calls"] = serialized_calls
        return AgentDecision(
            assistant_message=assistant_message,
            content=content,
            tool_calls=requested_calls,
            usage=RagTokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
            ),
        )


@lru_cache
def get_tool_calling_provider() -> ToolCallingProvider:
    return QwenToolCallingProvider()


class DiagnosisState(TypedDict, total=False):
    session: Session
    project_id: str
    question: str
    messages: list[dict[str, Any]]
    pending_tool_calls: list[RequestedToolCall]
    tool_calls: list[ToolCallTrace]
    answer: str
    iterations: int
    max_iterations: int
    warnings: list[str]
    usage: RagTokenUsage
    started_at: float
    stream_events: bool


SYSTEM_PROMPT = """你是 RepoPilot 的代码仓库诊断 Agent。
你只能依据工具从当前仓库取得的证据回答，第一次必须调用至少一个工具。
优先使用 semantic_search 定位实现，再按需要使用 read_file、list_files 或
get_repository_stats 补充证据。不要猜测未读取的代码。工具失败时可以修正参数后重试。
最终使用中文，并严格按【诊断结论】【根因分析】【代码证据】【修复建议】【验证步骤】
五个部分组织回答；代码证据必须写出真实文件路径和行号，无法确认的内容要明确说明。"""


def _build_response(state: DiagnosisState) -> DiagnosisResponse:
    return DiagnosisResponse(
        project_id=state["project_id"],
        question=state["question"],
        answer=state.get("answer", ""),
        model=settings.chat_model_name,
        iterations=state.get("iterations", 0),
        duration_ms=int((perf_counter() - state["started_at"]) * 1000),
        usage=state.get("usage", RagTokenUsage()),
        tool_calls=state.get("tool_calls", []),
        warnings=state.get("warnings", []),
    )


def agent_node(state: DiagnosisState) -> dict[str, object]:
    # 最后一次模型调用禁止继续选工具，保证图能在配置的最大轮数内生成最终答案。
    allow_tools = state.get("iterations", 0) < state["max_iterations"] - 1
    force_tool = not state.get("tool_calls") and allow_tools
    decision = get_tool_calling_provider().decide(
        state["messages"],
        allow_tools=allow_tools,
        force_tool=force_tool,
    )
    warnings = list(state.get("warnings", []))
    previous_usage = state.get("usage", RagTokenUsage())
    usage = RagTokenUsage(
        prompt_tokens=previous_usage.prompt_tokens + decision.usage.prompt_tokens,
        completion_tokens=previous_usage.completion_tokens + decision.usage.completion_tokens,
        total_tokens=previous_usage.total_tokens + decision.usage.total_tokens,
    )
    pending_calls = decision.tool_calls if allow_tools else []
    answer = state.get("answer", "")
    if not pending_calls:
        answer = decision.content or "模型没有生成可用的诊断结论。"
        if not state.get("tool_calls"):
            warnings.append("模型没有成功调用仓库工具，本次结论缺少工具证据。")
    next_state: DiagnosisState = {
        "messages": [*state["messages"], decision.assistant_message],
        "pending_tool_calls": pending_calls,
        "answer": answer,
        "iterations": state.get("iterations", 0) + 1,
        "warnings": warnings,
        "usage": usage,
    }
    if state.get("stream_events"):
        writer = get_stream_writer()
        if pending_calls:
            writer(
                {
                    "type": "decision",
                    "iteration": next_state["iterations"],
                    "tool_calls": [
                        {
                            "call_id": call.call_id,
                            "name": call.name,
                            "arguments": call.arguments,
                        }
                        for call in pending_calls
                    ],
                }
            )
        else:
            complete_state: DiagnosisState = {**state, **next_state}
            writer(
                {
                    "type": "complete",
                    "response": _build_response(complete_state).model_dump(mode="json"),
                }
            )
    return next_state


def tools_node(state: DiagnosisState) -> dict[str, object]:
    messages = list(state["messages"])
    traces = list(state.get("tool_calls", []))
    for call in state.get("pending_tool_calls", []):
        if state.get("stream_events"):
            writer = get_stream_writer()
            writer(
                {
                    "type": "tool_start",
                    "call_id": call.call_id,
                    "name": call.name,
                    "arguments": call.arguments,
                }
            )
        execution = repository_tool_service.execute(
            state["session"],
            state["project_id"],
            call.call_id,
            call.name,
            call.arguments,
        )
        traces.append(execution.trace)
        if state.get("stream_events"):
            writer(
                {
                    "type": "tool_complete",
                    "trace": execution.trace.model_dump(mode="json"),
                }
            )
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call.call_id,
                "content": execution.model_content,
            }
        )
    return {"messages": messages, "tool_calls": traces, "pending_tool_calls": []}


def route_after_agent(state: DiagnosisState) -> str:
    return "tools" if state.get("pending_tool_calls") else END


def build_diagnosis_graph():
    builder = StateGraph(DiagnosisState)
    builder.add_node("agent", agent_node)
    builder.add_node("tools", tools_node)
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", route_after_agent, {"tools": "tools", END: END})
    builder.add_edge("tools", "agent")
    return builder.compile()


diagnosis_graph = build_diagnosis_graph()


class DiagnosisService:
    @staticmethod
    def _initial_state(
        session: Session,
        project_id: str,
        question: str,
        max_iterations: int,
        *,
        stream_events: bool,
    ) -> DiagnosisState:
        return {
            "session": session,
            "project_id": project_id,
            "question": question,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
            "pending_tool_calls": [],
            "tool_calls": [],
            "answer": "",
            "iterations": 0,
            "max_iterations": max_iterations,
            "warnings": [],
            "usage": RagTokenUsage(),
            "started_at": perf_counter(),
            "stream_events": stream_events,
        }

    @staticmethod
    def diagnose(
        session: Session,
        project_id: str,
        question: str,
        max_iterations: int,
    ) -> DiagnosisResponse:
        result = diagnosis_graph.invoke(
            DiagnosisService._initial_state(
                session,
                project_id,
                question,
                max_iterations,
                stream_events=False,
            )
        )
        return _build_response(result)

    @staticmethod
    def stream(
        session: Session,
        project_id: str,
        question: str,
        max_iterations: int,
    ):
        """运行诊断图，并实时产出模型决策、工具执行和最终结果事件。"""
        yield {
            "type": "start",
            "question": question,
            "max_iterations": max_iterations,
        }
        for part in diagnosis_graph.stream(
            DiagnosisService._initial_state(
                session,
                project_id,
                question,
                max_iterations,
                stream_events=True,
            ),
            stream_mode="custom",
            version="v2",
        ):
            if part["type"] == "custom":
                yield part["data"]


diagnosis_service = DiagnosisService()
