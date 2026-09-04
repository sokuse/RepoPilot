# RepoPilot

RepoPilot 是一个面向多仓库研发团队的软件维护知识、故障诊断与 Agent 评测平台。

当前仓库已完成第八阶段：在仓库采集、可追溯 RAG、Function Call 和多 Agent 诊断之上，
新增短期对话上下文、长期向量记忆、历史诊断召回与回答反馈闭环。

## 目录

```text
backend/   Python 3.11+、FastAPI，后续承载 LangChain/LangGraph/RAG/MCP
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
- 使用 Qdrant 本地持久化模式按项目隔离向量
- 通过知识检索页面返回带相似度、文件路径和行号的代码片段
- 使用 LangGraph 编排“语义召回 → Qwen 生成 → 引用校验”工作流
- 通过 `POST /api/v1/projects/{project_id}/rag/stream` 以 SSE 实时推送召回、Token 和校验事件
- 生成中文仓库回答，并把 `[S编号]` 映射回真实文件与行号
- 将每次问答的状态、模型、耗时和 Token 用量持久化到 SQLite
- 保存回答当时的检索切片、引用和 LangGraph 步骤快照，避免重建索引后旧依据丢失
- 通过 `GET /api/v1/projects/{project_id}/rag/runs` 查询运行历史，并可读取单次运行详情
- 在知识检索页面回看已完成或失败的 RAG 运行记录
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

默认地址：

- 前端：http://localhost:5173
- 后端：http://localhost:8000
- OpenAPI：http://localhost:8000/docs
