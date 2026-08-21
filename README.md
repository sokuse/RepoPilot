# RepoPilot

RepoPilot 是一个面向多仓库研发团队的软件维护知识、故障诊断与 Agent 评测平台。

当前仓库处于第一阶段：搭建 Vue 3 前端与 Python FastAPI 后端，先完成项目接入和可观测的 API 基础。

## 目录

```text
backend/   Python 3.11+、FastAPI，后续承载 LangChain/LangGraph/RAG/MCP
frontend/  Vue 3、TypeScript、Vite
```

## 本地启动

后端：

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
uvicorn repopilot.main:app --reload
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

