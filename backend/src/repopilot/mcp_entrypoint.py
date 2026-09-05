import os
from pathlib import Path


def main() -> None:
    """从任意 MCP Host 工作目录安全启动，并让相对配置仍指向 backend。"""
    backend_dir = Path(__file__).resolve().parents[2]
    os.chdir(backend_dir)

    # 必须在切换目录后导入，否则 SQLite 引擎会绑定到 MCP Host 的工作目录。
    from repopilot.mcp_server import main as run_server

    run_server()


if __name__ == "__main__":
    main()
