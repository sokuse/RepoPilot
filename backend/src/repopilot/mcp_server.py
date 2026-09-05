import json
from typing import Annotated, Any, Literal

import httpx
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from repopilot.core.config import settings
from repopilot.schemas.conversation import MemorySearchResult
from repopilot.schemas.evaluation import EvaluationRunDetail, EvaluationRunSummary
from repopilot.schemas.project import ProjectResponse
from repopilot.schemas.rag import RagRunSummary
from repopilot.schemas.retrieval import SemanticSearchResult

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False)

mcp = MCPServer(
    "RepoPilot",
    instructions=(
        "RepoPilot 提供已接入代码仓库的语义检索、受限文件读取、历史记忆、"
        "RAG 记录、诊断与评测报告。调用仓库工具前先使用 list_projects 获取 project_id。"
    ),
)


class ProjectListResult(BaseModel):
    projects: list[ProjectResponse]


class RepositorySearchResult(BaseModel):
    project_id: str
    query: str
    results: list[SemanticSearchResult]


class RepositoryFileResult(BaseModel):
    project_id: str
    path: str
    start_line: int
    end_line: int
    content: str
    truncated: bool


class MemorySearchToolResult(BaseModel):
    project_id: str
    query: str
    results: list[MemorySearchResult]


class RagHistoryResult(BaseModel):
    project_id: str
    runs: list[RagRunSummary]


class EvaluationRunListResult(BaseModel):
    project_id: str
    runs: list[EvaluationRunSummary]


class DiagnosisToolResult(BaseModel):
    project_id: str
    mode: Literal["single", "multi"]
    answer: str
    evidence_files: list[str]
    total_tokens: int
    duration_ms: int
    warnings: list[str]


def _api_request(
    method: str,
    path: str,
    payload: dict[str, object] | None = None,
) -> Any:
    """所有 MCP 工具统一通过 FastAPI，避免第二个进程直接占用本地 Qdrant。"""
    url = f"{settings.mcp_api_base_url.rstrip('/')}/{path.lstrip('/')}"
    try:
        response = httpx.request(method, url, json=payload, timeout=300)
    except httpx.RequestError as error:
        raise ValueError("无法连接 RepoPilot FastAPI，请确认后端已在 8000 端口启动") from error
    if response.is_error:
        try:
            detail = response.json().get("detail", response.text)
        except (ValueError, AttributeError):
            detail = response.text
        raise ValueError(f"RepoPilot API 请求失败（{response.status_code}）：{detail}")
    if response.status_code == 204:
        return None
    return response.json()


def _evidence_files(tool_calls: list[dict[str, object]]) -> list[str]:
    paths: set[str] = set()
    for call in tool_calls:
        arguments = call.get("arguments", {})
        path = arguments.get("path") if isinstance(arguments, dict) else None
        if isinstance(path, str):
            paths.add(path)
        try:
            payload = json.loads(str(call.get("result", "")))
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(payload, dict):
            direct_path = payload.get("path")
            if isinstance(direct_path, str):
                paths.add(direct_path)
            results = payload.get("results", [])
            if isinstance(results, list):
                paths.update(
                    item["source_path"]
                    for item in results
                    if isinstance(item, dict) and isinstance(item.get("source_path"), str)
                )
    return sorted(paths)


@mcp.tool(
    title="列出 RepoPilot 项目",
    annotations=READ_ONLY,
)
def list_projects() -> ProjectListResult:
    """列出 RepoPilot 中的全部仓库项目及状态，用于获得其他工具需要的 project_id。"""
    payload = _api_request("GET", "/projects")
    return ProjectListResult(projects=[ProjectResponse.model_validate(row) for row in payload])


@mcp.tool(
    title="语义搜索代码仓库",
    annotations=READ_ONLY,
)
def search_repository(
    project_id: Annotated[str, Field(description="list_projects 返回的项目 ID")],
    query: Annotated[str, Field(min_length=2, max_length=1000, description="自然语言问题")],
    limit: Annotated[int, Field(ge=1, le=12, description="最多返回多少个代码切片")] = 5,
) -> RepositorySearchResult:
    """在指定项目的 Qdrant 代码索引中搜索，返回文件路径、行号和代码片段。"""
    payload = _api_request(
        "POST",
        f"/projects/{project_id}/index/search",
        {"query": query, "limit": limit},
    )
    return RepositorySearchResult.model_validate(payload)


@mcp.tool(
    title="读取仓库文件",
    annotations=READ_ONLY,
)
def read_repository_file(
    project_id: Annotated[str, Field(description="list_projects 返回的项目 ID")],
    path: Annotated[str, Field(min_length=1, max_length=1000, description="仓库相对路径")],
    start_line: Annotated[int, Field(ge=1)] = 1,
    end_line: Annotated[int, Field(ge=1)] = 200,
) -> RepositoryFileResult:
    """读取已扫描仓库文件的指定行范围；不能访问仓库外路径，单次最多 200 行。"""
    payload = _api_request(
        "POST",
        f"/projects/{project_id}/tools/read-file",
        {"path": path, "start_line": start_line, "end_line": end_line},
    )
    return RepositoryFileResult.model_validate(payload)


@mcp.tool(
    title="搜索项目历史记忆",
    annotations=READ_ONLY,
)
def search_project_memory(
    project_id: Annotated[str, Field(description="list_projects 返回的项目 ID")],
    query: Annotated[str, Field(min_length=2, max_length=2000)],
    limit: Annotated[int, Field(ge=1, le=10)] = 4,
) -> MemorySearchToolResult:
    """搜索指定项目的历史问答、用户反馈和过去诊断记录。"""
    payload = _api_request(
        "POST",
        f"/projects/{project_id}/conversations/memory/search",
        {"query": query, "limit": limit},
    )
    return MemorySearchToolResult(project_id=project_id, query=query, results=payload)


@mcp.tool(
    title="读取 RAG 问答历史",
    annotations=READ_ONLY,
)
def get_rag_history(
    project_id: Annotated[str, Field(description="list_projects 返回的项目 ID")],
    limit: Annotated[int, Field(ge=1, le=100)] = 20,
) -> RagHistoryResult:
    """读取指定项目最近的 RAG 执行记录，包括模型、Token、耗时和引用数量。"""
    payload = _api_request("GET", f"/projects/{project_id}/rag/runs?limit={limit}")
    return RagHistoryResult(
        project_id=project_id,
        runs=[RagRunSummary.model_validate(run) for run in payload],
    )


@mcp.tool(title="诊断代码仓库")
def diagnose_repository(
    project_id: Annotated[str, Field(description="list_projects 返回的项目 ID")],
    question: Annotated[str, Field(min_length=2, max_length=2000)],
    mode: Literal["single", "multi"] = "single",
    max_iterations: Annotated[int, Field(ge=2, le=5)] = 3,
) -> DiagnosisToolResult:
    """让 RepoPilot Agent 调查仓库并形成诊断；multi 更严格，但耗时和 Token 更高。"""
    endpoint = "diagnosis/multi-agent" if mode == "multi" else "diagnosis"
    payload = _api_request(
        "POST",
        f"/projects/{project_id}/{endpoint}",
        {"question": question, "max_iterations": max_iterations},
    )
    return DiagnosisToolResult(
        project_id=project_id,
        mode=mode,
        answer=payload["final_answer"] if mode == "multi" else payload["answer"],
        evidence_files=_evidence_files(payload.get("tool_calls", [])),
        total_tokens=payload.get("usage", {}).get("total_tokens", 0),
        duration_ms=payload.get("duration_ms", 0),
        warnings=payload.get("warnings", []),
    )


@mcp.tool(
    title="列出评测实验",
    annotations=READ_ONLY,
)
def list_evaluation_runs(
    project_id: Annotated[str, Field(description="list_projects 返回的项目 ID")],
) -> EvaluationRunListResult:
    """列出指定项目的评测实验，以便取得 get_evaluation_result 所需的 run_id。"""
    payload = _api_request("GET", f"/projects/{project_id}/evaluations/runs")
    return EvaluationRunListResult(
        project_id=project_id,
        runs=[EvaluationRunSummary.model_validate(run) for run in payload],
    )


@mcp.tool(
    title="读取评测报告",
    annotations=READ_ONLY,
)
def get_evaluation_result(
    project_id: Annotated[str, Field(description="list_projects 返回的项目 ID")],
    run_id: Annotated[str, Field(description="评测实验 ID")],
) -> EvaluationRunDetail:
    """读取一份已经完成的 Agent/RAG 评测报告及其单题得分。"""
    payload = _api_request("GET", f"/projects/{project_id}/evaluations/runs/{run_id}")
    return EvaluationRunDetail.model_validate(payload)


def main() -> None:
    """启动 RepoPilot MCP Server；stdio 模式下不要向 stdout 打印日志。"""
    if settings.mcp_transport == "streamable-http":
        mcp.run(
            transport="streamable-http",
            host=settings.mcp_host,
            port=settings.mcp_port,
            streamable_http_path="/mcp",
        )
    else:
        mcp.run()


if __name__ == "__main__":
    main()
