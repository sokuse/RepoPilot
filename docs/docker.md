# RepoPilot Docker Compose 部署

该 Compose 配置面向本地演示和简历项目，包含三个默认服务：

```text
浏览器 → Nginx（Vue） → FastAPI → SQLite
                            └──────→ Qdrant
```

- `frontend`：构建 Vue 后由 Nginx 提供静态页面，并将 `/api` 转发到后端。
- `backend`：运行 FastAPI，负责仓库采集、RAG、Agent、评测和数据访问。
- `qdrant`：独立向量数据库，通过命名卷持久化向量。
- `mcp`：可选的 Streamable HTTP MCP 服务，默认不启动。

## 首次启动

需要先安装 Docker Desktop，并确保 Docker Engine 正在运行。

如果还没有 `backend/.env`，从示例创建：

```powershell
Copy-Item backend/.env.example backend/.env
```

编辑 `backend/.env`，至少填写自己的百炼 API Key：

```env
REPOPILOT_QWEN_API_KEY=你的百炼APIKey
```

在项目根目录执行：

```powershell
docker compose up --build -d
```

查看状态和日志：

```powershell
docker compose ps
docker compose logs -f backend
```

启动完成后访问：

- RepoPilot：http://localhost:5173
- FastAPI OpenAPI：http://localhost:8000/docs
- Qdrant Dashboard：http://localhost:6333/dashboard

## 停止与重新构建

停止容器但保留数据：

```powershell
docker compose down
```

代码或依赖变化后重新构建：

```powershell
docker compose up --build -d
```

`docker compose down -v` 会同时删除 SQLite、仓库副本和 Qdrant 向量卷，属于清空数据操作，
不要在需要保留项目记录时使用。

## 数据保存在哪里

Compose 使用两个 Docker 命名卷：

- `repopilot_data`：SQLite 数据库和已克隆仓库。
- `qdrant_data`：代码向量和长期记忆向量。

这些数据不会提交到 Git。原来 `backend/repopilot.db` 和 `backend/data/qdrant` 中的本地开发数据
也不会自动迁移到 Docker 卷，因此第一次使用 Docker 时看到空项目列表是正常的。

## 启动 MCP 服务

需要通过 HTTP 连接 RepoPilot MCP 时，启用 `mcp` profile：

```powershell
docker compose --profile mcp up --build -d
```

MCP 地址为 `http://localhost:8001/mcp`。该地址当前没有身份认证，只绑定到本机回环地址，
不应直接暴露到公网。

## 关闭开发者实验室

正式演示普通用户界面时，可以在构建前设置：

```powershell
$env:VITE_ENABLE_DEVELOPER_LAB="false"
docker compose build frontend
docker compose up -d
```

恢复开发者实验室时，将值改回 `true` 并重新构建前端。

## GitHub 代理注意事项

容器里的 `127.0.0.1` 指向容器自身，不是 Windows 主机。如果梯子监听主机的 `7890` 端口，
Docker 环境中通常应在 `backend/.env` 配置：

```env
REPOPILOT_GIT_PROXY_URL=http://host.docker.internal:7890
```

同时需要允许 Docker Desktop 访问该代理端口。代理不需要时保持该配置为空。
