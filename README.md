# RepoPilot

RepoPilot 是一个面向多仓库研发团队的软件维护知识、故障诊断与 Agent 评测平台。

当前仓库已完成仓库采集、可追溯 RAG、Function Call、多 Agent 诊断、长期记忆、
自动评测与 MCP Server，并提供 Vue、FastAPI、Qdrant 的 Docker Compose 一键环境。

## 目录

```text
backend/   Python 3.11+、FastAPI，承载 LangGraph/RAG/Agent/MCP
frontend/  Vue 3、TypeScript、Vite
```

## 当前能力

- 创建、查询和删除仓库项目
- 拒绝重复接入同一个仓库
- SQLite 开发数据库（`backend/repopilot.db`，不会提交到 Git）
- FastAPI 自动生成 OpenAPI 文档
- Vue 项目工作台与后端错误反馈
- 隔离数据库的 API 自动化测试
- 后台浅克隆公开 GitHub 仓库
- 按扩展名、目录、文件大小和二进制特征过滤代码文件
- 保存文件路径、语言、大小和 SHA-256 元数据
- 展示仓库文件数量、体积和主要语言
- Python AST、Markdown 标题感知及 LangChain 语言感知递归切片
- 保存每个知识切片的源文件、起止行号、符号名、策略和内容哈希
- 通过页面生成/重建切片，并查看仓库级切片统计
- 调用百炼 `text-embedding-v4` 生成 1024 维文本与代码向量
- 支持 Qdrant 嵌入式开发模式和独立服务模式，并按项目隔离向量
- 通过知识检索页面返回带相似度、文件路径和行号的代码片段
- 使用 LangGraph 编排“语义召回 → Qwen 生成 → 引用校验”工作流
- 通过 `POST /api/v1/projects/{project_id}/rag/stream` 以 SSE 实时推送召回、Token 和校验事件
- 生成中文仓库回答，并把 `[S编号]` 映射回真实文件与行号
- 将每次问答的状态、模型、耗时和 Token 用量持久化到 SQLite
- 保存回答当时的检索切片、引用和 LangGraph 步骤快照，避免重建索引后旧依据丢失
- 通过 `GET /api/v1/projects/{project_id}/rag/runs` 查询运行历史，并可读取单次运行详情
- 提供语义搜索、读取仓库文件、列出文件和仓库统计四个只读 Agent 工具
- 由 Qwen 自主选择工具，LangGraph 循环执行“模型决策 → 工具调用 → 继续分析”
- 通过 `POST /api/v1/projects/{project_id}/diagnosis` 运行有轮数上限的智能诊断
- 通过 `POST /api/v1/projects/{project_id}/diagnosis/stream` 实时推送决策和工具执行事件
- 在智能诊断页面展示调查时间线、结构化结论、累计 Token 和 Function Call 轨迹
- 通过外层 LangGraph 串联规划 Agent、工具调查 Agent 和证据审查 Agent
- 保留单 Agent 普通/流式接口，并新增 `POST /api/v1/projects/{project_id}/diagnosis/multi-agent`
- 对调查草稿进行证据评分与修订，审查格式异常时安全回退到原始草稿
- 在智能诊断页面切换单 Agent 实时模式与多 Agent 审查模式
- 通过会话与消息表保存多轮 RAG 问答，并将 Assistant 消息关联到原始 RAG 运行记录
- 在知识检索页面创建、切换和查看历史对话，并记录回答“有帮助/没帮助”的反馈
- 将问答和诊断结论切片、Embedding 后写入独立的 `repopilot_memories` Qdrant collection
- 新问题同时检索仓库代码、当前对话最近消息、历史对话和过去诊断记录
- 返回并展示 `[M编号]` 历史记忆来源、相似度和长期记忆索引数量
- 创建包含问题、期望文件和必要关键词的项目级评测数据集
- 对比纯检索、RAG、单 Agent 和多 Agent 四种运行模式
- 自动计算文件召回、关键词覆盖、证据可信度、综合得分和通过率
- 保存每道题的答案、召回文件、Token、耗时、错误以及模型与切片策略快照
- 在评测实验页面查看单题明细和历史实验，支持使用同一测试集进行横向比较
- 前端区分普通用户工作区与开发者实验室，可一键隐藏切片、模型、Token 和评测细节
- 正式部署时可通过 `VITE_ENABLE_DEVELOPER_LAB=false` 关闭实验室入口和路由访问
- 使用官方 Python MCP SDK v2，通过类型标注自动生成工具输入和结构化输出 Schema
- 通过 MCP 暴露项目列表、仓库搜索、受限文件读取、长期记忆、RAG 历史和诊断能力
- 通过 MCP 查询历史评测实验与单题报告，默认使用本地 `stdio` 传输
- 可切换为仅监听 `127.0.0.1` 的 Streamable HTTP，且不再使用已被取代的 SSE 传输
- 使用 Docker Compose 一键启动 Vue、FastAPI 和独立 Qdrant，并通过命名卷持久化数据

## 本地启动

后端：

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
uvicorn repopilot.main:app --reload
```

在 `backend/.env` 中配置百炼 API Key（该文件不会提交到 Git）：

```env
REPOPILOT_QWEN_API_KEY=你的百炼APIKey
```

前端：

```powershell
cd frontend
npm install
npm run dev
```

本地学习默认保留开发者实验室。面向普通用户构建时，可以在 `frontend/.env.production`
中关闭内部评测与技术细节入口：

```env
VITE_ENABLE_DEVELOPER_LAB=false
```

默认地址：

- 前端：http://localhost:5173
- 后端：http://localhost:8000
- OpenAPI：http://localhost:8000/docs

## Docker 一键启动

先确认 `backend/.env` 已填写 `REPOPILOT_QWEN_API_KEY`，然后在项目根目录执行：

```powershell
docker compose up --build -d
```

访问 http://localhost:5173。Docker 环境使用独立 Qdrant 服务，本地 PyCharm 开发仍可继续
使用原来的嵌入式 Qdrant，不会互相覆盖。容器结构、数据卷、MCP profile 和代理配置见
[Docker Compose 部署](docs/docker.md)。

## MCP Server

先按上面的方式启动 FastAPI。安装后，MCP 客户端可以启动本地 stdio MCP Server：

```powershell
cd backend
.venv\Scripts\repopilot-mcp.exe
```

stdio 模式会等待 MCP 客户端通过标准输入输出通信，因此终端没有普通输出是正常现象。
MCP 工具通过 FastAPI 统一访问 SQLite 和嵌入式 Qdrant，避免多个进程争用向量数据库。
客户端配置、工具清单和安全边界见 [RepoPilot MCP 接入](docs/mcp.md)。
