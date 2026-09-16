from repopilot.models.repository_file import RepositoryFile
from repopilot.services.repository_tool_service import repository_tool_service


class FakeSession:
    def __init__(self, *repository_files: RepositoryFile) -> None:
        self.repository_files = repository_files

    def scalar(self, _statement):
        return self.repository_files[0]

    def scalars(self, _statement):
        return self.repository_files


def test_read_file_tool_reads_numbered_lines_inside_repository(tmp_path, monkeypatch) -> None:
    project_id = "project-1"
    repository_root = tmp_path / project_id
    repository_root.mkdir()
    (repository_root / "app.py").write_text("first\nsecond\nthird\n", encoding="utf-8")
    monkeypatch.setattr(
        "repopilot.services.repository_tool_service.settings.repository_storage_path",
        tmp_path,
    )
    session = FakeSession(
        RepositoryFile(
            project_id=project_id,
            path="app.py",
            extension=".py",
            language="Python",
            size_bytes=19,
            content_sha256="sha",
        )
    )

    execution = repository_tool_service.execute(
        session,
        project_id,
        "call-1",
        "read_file",
        {"path": "app.py", "start_line": 2, "end_line": 3},
    )

    assert execution.trace.success is True
    assert "second" in execution.trace.result
    assert "    2:" in execution.trace.result


def test_read_file_tool_rejects_path_outside_repository(tmp_path, monkeypatch) -> None:
    project_id = "project-1"
    (tmp_path / project_id).mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("secret", encoding="utf-8")
    monkeypatch.setattr(
        "repopilot.services.repository_tool_service.settings.repository_storage_path",
        tmp_path,
    )
    session = FakeSession(
        RepositoryFile(
            project_id=project_id,
            path="../secret.txt",
            extension=".txt",
            language="Text",
            size_bytes=6,
            content_sha256="sha",
        )
    )

    execution = repository_tool_service.execute(
        session,
        project_id,
        "call-2",
        "read_file",
        {"path": "../secret.txt", "start_line": 1, "end_line": 2},
    )

    assert execution.trace.success is False
    assert "路径不安全" in execution.trace.result


def test_grep_repository_returns_path_line_and_column(tmp_path, monkeypatch) -> None:
    project_id = "project-1"
    repository_root = tmp_path / project_id
    source_root = repository_root / "src"
    source_root.mkdir(parents=True)
    (source_root / "service.py").write_text(
        "class ProjectService:\n    def create_project(self):\n        pass\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "repopilot.services.repository_tool_service.settings.repository_storage_path",
        tmp_path,
    )
    session = FakeSession(
        RepositoryFile(
            project_id=project_id,
            path="src/service.py",
            extension=".py",
            language="Python",
            size_bytes=62,
            content_sha256="sha",
        )
    )

    execution = repository_tool_service.execute(
        session,
        project_id,
        "call-3",
        "grep_repository",
        {
            "pattern": "project(service|repository)",
            "path_prefix": "src/",
            "case_sensitive": False,
        },
    )

    assert execution.trace.success is True
    assert '"path": "src/service.py"' in execution.trace.result
    assert '"line_number": 1' in execution.trace.result
    assert '"column": 7' in execution.trace.result
