import re
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from time import perf_counter
from typing import Protocol, TypedDict
from uuid import UUID

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from openai import OpenAI
from sqlalchemy.orm import Session

from repopilot.core.config import settings
from repopilot.schemas.rag import (
    RagAnswerResponse,
    RagCitation,
    RagExecutionStep,
    RagTokenUsage,
)
from repopilot.schemas.retrieval import SemanticSearchResult
from repopilot.services.rag_run_service import rag_run_service
from repopilot.services.vector_search_service import vector_search_service

SOURCE_REFERENCE = re.compile(r"\[S(\d+)]")


class ChatConfigurationError(Exception):
    """Qwen 对话模型所需的 API Key 尚未配置。"""


@dataclass(frozen=True)
class ChatAnswer:
    text: str
    usage: RagTokenUsage


@dataclass(frozen=True)
class ChatStreamPart:
    delta: str = ""
    usage: RagTokenUsage | None = None


class ChatProvider(Protocol):
    def answer(self, question: str, context: str) -> ChatAnswer: ...

    def stream_answer(self, question: str, context: str) -> Iterator[ChatStreamPart]: ...


class QwenChatProvider:
    def __init__(self) -> None:
        api_key = settings.qwen_api_key
        if not api_key:
            raise ChatConfigurationError
        self.client = OpenAI(
            api_key=api_key,
            base_url=settings.embedding_api_base_url,
        )

    @staticmethod
    def _messages(question: str, context: str) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    "你是 RepoPilot 的代码仓库分析助手。只能依据给定的检索资料回答，"
                    "不得使用资料之外的事实。每个关键结论后必须使用 [S1]、[S2] 形式"
                    "标注来源。如果资料不足，请明确说明无法从当前仓库确认。使用中文，"
                    "先给结论，再解释关键调用链或实现细节。"
                ),
            },
            {
                "role": "user",
                "content": f"问题：\n{question}\n\n检索资料：\n{context}",
            },
        ]

    @staticmethod
    def _usage(usage) -> RagTokenUsage:
        if usage is None:
            return RagTokenUsage()
        return RagTokenUsage(
            prompt_tokens=usage.prompt_tokens or 0,
            completion_tokens=usage.completion_tokens or 0,
            total_tokens=usage.total_tokens or 0,
        )

    def answer(self, question: str, context: str) -> ChatAnswer:
        response = self.client.chat.completions.create(
            model=settings.chat_model_name,
            temperature=settings.rag_temperature,
            messages=self._messages(question, context),
        )
        content = response.choices[0].message.content
        return ChatAnswer(
            text=content.strip() if content else "模型没有返回可用答案。",
            usage=self._usage(response.usage),
        )

    def stream_answer(self, question: str, context: str) -> Iterator[ChatStreamPart]:
        # 百炼兼容 OpenAI 流式协议，每个 chunk 只携带本次新增的文本。
        stream = self.client.chat.completions.create(
            model=settings.chat_model_name,
            temperature=settings.rag_temperature,
            messages=self._messages(question, context),
            stream=True,
            stream_options={"include_usage": True},
        )
        for chunk in stream:
            if chunk.usage is not None:
                yield ChatStreamPart(usage=self._usage(chunk.usage))
            if not chunk.choices:
                continue
            content = chunk.choices[0].delta.content
            if content:
                yield ChatStreamPart(delta=content)


@lru_cache
def get_chat_provider() -> ChatProvider:
    return QwenChatProvider()


class RagState(TypedDict, total=False):
    session: Session
    project_id: str
    question: str
    retrieval_limit: int
    retrieved_chunks: list[SemanticSearchResult]
    context: str
    answer: str
    citations: list[RagCitation]
    steps: list[RagExecutionStep]
    warnings: list[str]
    stream_tokens: bool
    usage: RagTokenUsage


# 语义召回，负责检索并添加上下文。
def retrieve_node(state: RagState) -> dict[str, object]:
    response = vector_search_service.search(
        state["session"],
        state["project_id"],
        state["question"],
        state["retrieval_limit"],
        None,
    )
    context_parts: list[str] = []
    context_chars = 0
    selected_chunks: list[SemanticSearchResult] = []
    for index, result in enumerate(response.results, start=1):
        source = (
            f"[S{index}] 文件：{result.source_path}，行号：{result.start_line}-"
            f"{result.end_line}，符号：{result.symbol_name or '无'}，"
            f"相似度：{result.score:.4f}\n{result.content}"
        )
        if selected_chunks and context_chars + len(source) > settings.rag_max_context_chars:
            break
        context_parts.append(source)
        selected_chunks.append(result)
        context_chars += len(source)

    step = RagExecutionStep(
        name="retrieve",
        label="语义召回",
        detail=f"从 Qdrant 召回 {len(selected_chunks)} 个相关知识切片",
    )
    if state.get("stream_tokens"):
        writer = get_stream_writer()
        writer(
            {
                "type": "retrieval",
                "retrieved_chunks": [chunk.model_dump(mode="json") for chunk in selected_chunks],
                "step": step.model_dump(mode="json"),
            }
        )

    return {
        "retrieved_chunks": selected_chunks,
        "context": "\n\n".join(context_parts),
        "steps": [step],
    }


# 根据召回上下文生成回答，并记录模型返回的 Token 用量。
def generate_node(state: RagState) -> dict[str, object]:
    provider = get_chat_provider()
    if state.get("stream_tokens"):
        writer = get_stream_writer()
        answer_parts: list[str] = []
        usage = RagTokenUsage()
        for part in provider.stream_answer(state["question"], state["context"]):
            if part.delta:
                answer_parts.append(part.delta)
                writer({"type": "token", "delta": part.delta})
            if part.usage is not None:
                usage = part.usage
        answer = "".join(answer_parts).strip() or "模型没有返回可用答案。"
    else:
        result = provider.answer(state["question"], state["context"])
        answer = result.text
        usage = result.usage

    step = RagExecutionStep(
        name="generate",
        label="Qwen 生成",
        detail=f"使用 {settings.chat_model_name} 基于检索上下文生成答案",
    )
    if state.get("stream_tokens"):
        writer({"type": "step", "step": step.model_dump(mode="json")})

    return {
        "answer": answer,
        "usage": usage,
        "steps": [*state.get("steps", []), step],
    }


# 校验模型引用，并添加可信引用和警告。
def validate_node(state: RagState) -> dict[str, object]:
    chunks = state["retrieved_chunks"]
    referenced_indexes = {
        int(match.group(1))
        for match in SOURCE_REFERENCE.finditer(state["answer"])
        if 1 <= int(match.group(1)) <= len(chunks)
    }
    citations = [
        RagCitation(
            source_id=f"S{index}",
            chunk_id=chunks[index - 1].chunk_id,
            source_path=chunks[index - 1].source_path,
            start_line=chunks[index - 1].start_line,
            end_line=chunks[index - 1].end_line,
            symbol_name=chunks[index - 1].symbol_name,
            score=chunks[index - 1].score,
        )
        for index in sorted(referenced_indexes)
    ]
    warnings: list[str] = []
    if not citations:
        warnings.append("模型答案没有生成有效的 [S编号] 引用，请结合下方检索依据核对。")

    step = RagExecutionStep(
        name="validate",
        label="引用校验",
        detail=f"校验到 {len(citations)} 个可追溯来源",
    )
    steps = [*state.get("steps", []), step]
    if state.get("stream_tokens"):
        response = RagAnswerResponse(
            project_id=state["project_id"],
            question=state["question"],
            answer=state["answer"],
            citations=citations,
            retrieved_chunks=chunks,
            steps=steps,
            warnings=warnings,
            usage=state.get("usage", RagTokenUsage()),
        )
        writer = get_stream_writer()
        writer({"type": "complete", "response": response.model_dump(mode="json")})

    return {
        "citations": citations,
        "warnings": warnings,
        "steps": steps,
    }


def build_rag_graph():
    builder = StateGraph(RagState)
    builder.add_node("retrieve", retrieve_node)
    builder.add_node("generate", generate_node)
    builder.add_node("validate", validate_node)
    builder.add_edge(START, "retrieve")
    builder.add_edge("retrieve", "generate")
    builder.add_edge("generate", "validate")
    builder.add_edge("validate", END)
    return builder.compile()


rag_graph = build_rag_graph()


class RagService:
    @staticmethod
    def ask(
        session: Session,
        project_id: str,
        question: str,
        retrieval_limit: int,
    ) -> RagAnswerResponse:
        run = rag_run_service.start(session, project_id, question, retrieval_limit)
        started = perf_counter()
        try:
            result = rag_graph.invoke(
                {
                    "session": session,
                    "project_id": project_id,
                    "question": question,
                    "retrieval_limit": retrieval_limit,
                    "steps": [],
                    "warnings": [],
                }
            )
            response = RagAnswerResponse(
                run_id=run.id,
                project_id=project_id,
                question=question,
                answer=result["answer"],
                citations=result.get("citations", []),
                retrieved_chunks=result["retrieved_chunks"],
                steps=result.get("steps", []),
                warnings=result.get("warnings", []),
                usage=result.get("usage", RagTokenUsage()),
                duration_ms=int((perf_counter() - started) * 1000),
            )
            rag_run_service.complete(session, run.id, response)
            return response
        except Exception as error:
            rag_run_service.fail(
                session,
                run.id,
                error,
                int((perf_counter() - started) * 1000),
            )
            raise

    @staticmethod
    def stream(
        session: Session,
        project_id: str,
        question: str,
        retrieval_limit: int,
    ) -> Iterator[dict[str, object]]:
        """运行同一张 LangGraph，并向 HTTP 层逐个产出自定义流事件。"""
        run = rag_run_service.start(session, project_id, question, retrieval_limit)
        started = perf_counter()
        yield {"type": "run", "run_id": run.id}
        try:
            for part in rag_graph.stream(
                {
                    "session": session,
                    "project_id": project_id,
                    "question": question,
                    "retrieval_limit": retrieval_limit,
                    "steps": [],
                    "warnings": [],
                    "stream_tokens": True,
                },
                stream_mode="custom",
                version="v2",
            ):
                if part["type"] != "custom":
                    continue
                event = part["data"]
                if event.get("type") == "complete":
                    response = RagAnswerResponse.model_validate(event["response"]).model_copy(
                        update={
                            "run_id": UUID(run.id),
                            "duration_ms": int((perf_counter() - started) * 1000),
                        }
                    )
                    rag_run_service.complete(session, run.id, response)
                    event = {"type": "complete", "response": response.model_dump(mode="json")}
                yield event
        except Exception as error:
            rag_run_service.fail(
                session,
                run.id,
                error,
                int((perf_counter() - started) * 1000),
            )
            raise


rag_service = RagService()
