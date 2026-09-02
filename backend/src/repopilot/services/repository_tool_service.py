import json
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from repopilot.core.config import settings
from repopilot.models.repository_file import RepositoryFile
from repopilot.schemas.diagnosis import ToolCallTrace
from repopilot.services.repository_ingestion_service import repository_ingestion_service
from repopilot.services.vector_search_service import vector_search_service

MAX_TOOL_RESULT_CHARS = 20_000


class SemanticSearchArguments(BaseModel):
    query: str = Field(min_length=2, max_length=1000)
    limit: int = Field(default=4, ge=1, le=5)


class ReadFileArguments(BaseModel):
    path: str = Field(min_length=1, max_length=1000)
    start_line: int = Field(default=1, ge=1)
    end_line: int = Field(default=200, ge=1)

    @model_validator(mode="after")
    def validate_line_range(self) -> "ReadFileArguments":
        if self.end_line < self.start_line:
            raise ValueError("end_line must not be smaller than start_line")
        if self.end_line - self.start_line > 199:
            raise ValueError("a single read_file call may read at most 200 lines")
        return self


class ListFilesArguments(BaseModel):
    prefix: str = Field(default="", max_length=500)
    limit: int = Field(default=50, ge=1, le=100)


@dataclass(frozen=True)
class ToolExecution:
    trace: ToolCallTrace
    model_content: str


# 这里使用 OpenAI 兼容的工具描述格式，Qwen 会根据 description 和 parameters 选择工具。
REPOSITORY_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "semantic_search",
            "description": "按自然语言语义检索当前代码仓库，返回相关代码片段、文件路径和行号。",
            "parameters": SemanticSearchArguments.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取当前仓库中一个已扫描文本文件的指定行范围，最多读取 200 行。",
            "parameters": ReadFileArguments.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "列出当前代码仓库的文件，可以用目录或文件名前缀缩小范围。",
            "parameters": ListFilesArguments.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_repository_stats",
            "description": "查看当前仓库的文件总数、总体积和语言分布。",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
]


class RepositoryToolService:
    @staticmethod
    def _repository_root(project_id: str) -> Path:
        storage_root = settings.repository_storage_path.resolve()
        repository_root = (storage_root / project_id).resolve()
        if repository_root.parent != storage_root:
            raise ValueError("Repository path escaped the configured storage directory")
        return repository_root

    @staticmethod
    def _read_file(session: Session, project_id: str, raw: dict[str, Any]) -> dict[str, Any]:
        arguments = ReadFileArguments.model_validate(raw)
        normalized_path = arguments.path.replace("\\", "/").lstrip("/")
        repository_file = session.scalar(
            select(RepositoryFile).where(
                RepositoryFile.project_id == project_id,
                RepositoryFile.path == normalized_path,
            )
        )
        if repository_file is None:
            raise ValueError("文件不在仓库已扫描清单中")

        repository_root = RepositoryToolService._repository_root(project_id)
        target = (repository_root / normalized_path).resolve()
        if not target.is_relative_to(repository_root) or not target.is_file():
            raise ValueError("文件不存在或路径不安全")

        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        selected = lines[arguments.start_line - 1 : arguments.end_line]
        numbered_content = "\n".join(
            f"{line_number:>5}: {line}"
            for line_number, line in enumerate(selected, start=arguments.start_line)
        )
        truncated = len(numbered_content) > MAX_TOOL_RESULT_CHARS
        if truncated:
            numbered_content = numbered_content[:MAX_TOOL_RESULT_CHARS] + "\n...内容已截断"
        actual_end = arguments.start_line + len(selected) - 1 if selected else arguments.start_line
        return {
            "path": normalized_path,
            "start_line": arguments.start_line,
            "end_line": actual_end,
            "content": numbered_content,
            "truncated": truncated,
        }

    @staticmethod
    def _list_files(session: Session, project_id: str, raw: dict[str, Any]) -> dict[str, Any]:
        arguments = ListFilesArguments.model_validate(raw)
        statement = select(RepositoryFile.path).where(RepositoryFile.project_id == project_id)
        if arguments.prefix:
            statement = statement.where(
                RepositoryFile.path.startswith(arguments.prefix, autoescape=True)
            )
        paths = list(
            session.scalars(statement.order_by(RepositoryFile.path).limit(arguments.limit))
        )
        return {"prefix": arguments.prefix, "count": len(paths), "files": paths}

    @staticmethod
    def _semantic_search(
        session: Session, project_id: str, raw: dict[str, Any]
    ) -> dict[str, Any]:
        arguments = SemanticSearchArguments.model_validate(raw)
        response = vector_search_service.search(
            session,
            project_id,
            arguments.query,
            arguments.limit,
            None,
        )
        return {
            "query": arguments.query,
            "count": len(response.results),
            "results": [item.model_dump(mode="json") for item in response.results],
        }

    @staticmethod
    def _repository_stats(session: Session, project_id: str) -> dict[str, Any]:
        return repository_ingestion_service.stats(session, project_id).model_dump(mode="json")

    def execute(
        self,
        session: Session,
        project_id: str,
        call_id: str,
        name: str,
        arguments: dict[str, Any],
    ) -> ToolExecution:
        started = perf_counter()
        try:
            if name == "semantic_search":
                payload = self._semantic_search(session, project_id, arguments)
                summary = f"语义检索返回 {payload['count']} 个相关切片"
            elif name == "read_file":
                payload = self._read_file(session, project_id, arguments)
                summary = (
                    f"读取 {payload['path']} 第 "
                    f"{payload['start_line']}-{payload['end_line']} 行"
                )
            elif name == "list_files":
                payload = self._list_files(session, project_id, arguments)
                summary = f"列出 {payload['count']} 个文件"
            elif name == "get_repository_stats":
                payload = self._repository_stats(session, project_id)
                summary = f"仓库包含 {payload['total_files']} 个文件"
            else:
                raise ValueError(f"不支持的工具：{name}")
            success = True
            result = json.dumps(payload, ensure_ascii=False)
        except (ValidationError, ValueError, OSError) as error:
            success = False
            summary = f"工具调用失败：{error}"
            result = json.dumps({"error": str(error)}, ensure_ascii=False)

        trace = ToolCallTrace(
            call_id=call_id,
            name=name,
            arguments=arguments,
            summary=summary,
            result=result,
            success=success,
            duration_ms=int((perf_counter() - started) * 1000),
        )
        return ToolExecution(trace=trace, model_content=result)


repository_tool_service = RepositoryToolService()
