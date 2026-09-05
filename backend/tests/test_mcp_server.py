import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters, stdio_client

from repopilot import mcp_server


def test_mcp_lists_tools_and_returns_projects(monkeypatch) -> None:
    now = datetime.now(UTC).isoformat()
    monkeypatch.setattr(
        mcp_server,
        "_api_request",
        lambda *_args: [
            {
                "id": "8b3f746e-763f-43ef-abd3-25c796191170",
                "name": "RepoPilot",
                "repository_url": "https://github.com/example/repopilot",
                "default_branch": "main",
                "status": "ready",
                "created_at": now,
                "updated_at": now,
            }
        ],
    )

    async def scenario() -> None:
        # 使用官方客户端进程内连接，验证工具发现和结构化返回值。
        async with Client(mcp_server.mcp) as client:
            tools = await client.list_tools()
            names = {tool.name for tool in tools.tools}
            assert {
                "list_projects",
                "search_repository",
                "read_repository_file",
                "search_project_memory",
                "get_rag_history",
                "diagnose_repository",
                "list_evaluation_runs",
                "get_evaluation_result",
            } <= names

            result = await client.call_tool("list_projects", {})
            assert result.is_error is False
            assert result.structured_content is not None
            assert result.structured_content["projects"][0]["name"] == "RepoPilot"

    asyncio.run(scenario())


def test_mcp_entrypoint_works_over_stdio() -> None:
    backend_dir = Path(__file__).resolve().parents[1]

    async def scenario() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "repopilot.mcp_entrypoint"],
            cwd=backend_dir,
        )
        async with Client(stdio_client(parameters)) as client:
            tools = await client.list_tools()
            assert any(tool.name == "search_repository" for tool in tools.tools)

    asyncio.run(scenario())
