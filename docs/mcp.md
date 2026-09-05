# RepoPilot MCP 接入

RepoPilot 使用官方 Python MCP SDK v2，将本地仓库知识、长期记忆、诊断和评测能力
提供给支持 MCP 的 AI 客户端。默认使用 `stdio`：客户端启动 MCP 子进程；该子进程再调用
已经运行的 RepoPilot FastAPI，由 FastAPI 统一访问 SQLite 和本地 Qdrant。

```text
AI 客户端 → MCP Server → FastAPI → SQLite / Qdrant / Qwen
```

使用 MCP 前必须先启动 FastAPI（默认 `http://127.0.0.1:8000`）。这种结构可以避免
FastAPI 和 MCP 两个进程同时打开同一个嵌入式 Qdrant 数据目录。

## 可用工具

| 工具 | 用途 |
| --- | --- |
| `list_projects` | 获取已接入项目以及其他工具需要的 `project_id` |
| `search_repository` | 语义检索代码，返回真实文件路径、行号和片段 |
| `read_repository_file` | 读取已扫描文件的指定行范围，最多 200 行 |
| `search_project_memory` | 检索历史问答、反馈和诊断记忆 |
| `get_rag_history` | 查看最近 RAG 运行的模型、Token、耗时和引用数 |
| `diagnose_repository` | 运行单 Agent 或多 Agent 仓库诊断 |
| `list_evaluation_runs` | 获取评测实验及其 ID |
| `get_evaluation_result` | 读取完整评测报告和单题结果 |

所有工具都不会修改仓库文件；`diagnose_repository` 会调用 Qwen 对话模型，
`search_repository` 和 `search_project_memory` 会调用 Qwen Embedding，因此这三个工具
都可能产生少量模型费用。其余工具只读取 RepoPilot 已保存的数据。

## 本地 stdio 配置

先在 `backend` 中安装项目：

```powershell
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

然后在 MCP 客户端中添加服务器。Windows 示例（路径需要替换成自己的绝对路径）：

```json
{
  "mcpServers": {
    "repopilot": {
      "command": "E:\\desktop\\agentProject\\backend\\.venv\\Scripts\\python.exe",
      "args": ["-m", "repopilot.mcp_entrypoint"]
    }
  }
}
```

配置完成后重启 MCP 客户端。客户端通常应先调用 `list_projects`，再把返回的
`project_id` 传给搜索、读取、诊断等工具。

## Streamable HTTP

需要把 MCP 作为本机服务运行时，在 `backend/.env` 中配置：

```env
REPOPILOT_MCP_TRANSPORT=streamable-http
REPOPILOT_MCP_HOST=127.0.0.1
REPOPILOT_MCP_PORT=8001
```

然后启动：

```powershell
.venv\Scripts\repopilot-mcp.exe
```

客户端连接地址为 `http://127.0.0.1:8001/mcp`。

当前 HTTP 模式没有实现身份认证，因此只应绑定 `127.0.0.1`，不要直接暴露到公网。
如果 FastAPI 地址发生变化，可以设置：

```env
REPOPILOT_MCP_API_BASE_URL=http://127.0.0.1:8000/api/v1
```

## 安全边界

- MCP 只能操作 RepoPilot 数据库中已经存在的项目。
- 文件读取必须命中仓库扫描清单，且路径必须位于对应仓库目录内。
- 单次文件读取最多 200 行，工具结果有长度限制。
- 没有提供写文件、执行 Shell、删除项目或修改 Git 仓库的工具。
- `stdio` 的标准输出属于 MCP 协议通道，服务代码不得使用 `print()` 输出日志。
