# RepoPilot

RepoPilot 是一个面向多仓库研发团队的软件维护知识、故障诊断与 Agent 评测平台。

当前仓库处于第四阶段：已完成仓库采集、可追溯知识切片、语义检索，
以及由 LangGraph 编排的 Qwen 流式 RAG 问答与引用校验链路。

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
