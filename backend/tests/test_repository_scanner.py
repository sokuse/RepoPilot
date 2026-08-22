import subprocess
from pathlib import Path

import pytest

from repopilot.core.config import settings
from repopilot.services.repository_ingestion_service import clone_repository
from repopilot.services.repository_scanner import scan_repository


def write_file(root: Path, relative_path: str, content: bytes) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_scanner_keeps_source_files_and_skips_noise(tmp_path: Path) -> None:
    write_file(tmp_path, "src/main.py", b"print('hello')\n")
    write_file(tmp_path, "README.md", b"# Demo\n")
    write_file(tmp_path, "Dockerfile", b"FROM python:3.11\n")
    write_file(tmp_path, "node_modules/dependency.js", b"ignored\n")
    write_file(tmp_path, "assets/image.png", b"\x89PNG\x00binary")
    write_file(tmp_path, "generated/large.txt", b"x" * 101)

    files = scan_repository(tmp_path, max_file_size_bytes=100)

    assert [file.path for file in files] == ["Dockerfile", "README.md", "src/main.py"]
    assert {file.language for file in files} == {"Dockerfile", "Markdown", "Python"}
    assert all(len(file.content_sha256) == 64 for file in files)


def test_shallow_clone_from_local_git_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=source, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@repopilot.local"],
        cwd=source,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "RepoPilot Test"],
        cwd=source,
        check=True,
    )
    write_file(source, "README.md", b"# Local repository\n")
    subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=source, check=True, capture_output=True)

    # 使用临时受控目录验证真实 Git 命令，不访问外部网络。
    storage = tmp_path / "repositories"
    monkeypatch.setattr(settings, "repository_storage_path", storage)
    target = storage / "project-id"

    clone_repository(source.as_uri(), "main", target)

    assert (target / "README.md").read_text(encoding="utf-8") == "# Local repository\n"
