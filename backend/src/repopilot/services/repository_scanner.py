from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

IGNORED_DIRECTORIES = {
    ".git",
    ".idea",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "target",
    "vendor",
    "venv",
}

LANGUAGE_BY_EXTENSION = {
    ".c": "C",
    ".cc": "C++",
    ".cpp": "C++",
    ".cs": "C#",
    ".css": "CSS",
    ".go": "Go",
    ".h": "C",
    ".hpp": "C++",
    ".html": "HTML",
    ".ini": "INI",
    ".java": "Java",
    ".js": "JavaScript",
    ".json": "JSON",
    ".jsx": "JavaScript",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".md": "Markdown",
    ".php": "PHP",
    ".ps1": "PowerShell",
    ".py": "Python",
    ".rb": "Ruby",
    ".rs": "Rust",
    ".rst": "reStructuredText",
    ".scss": "SCSS",
    ".sh": "Shell",
    ".sql": "SQL",
    ".svelte": "Svelte",
    ".toml": "TOML",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".txt": "Text",
    ".vue": "Vue",
    ".xml": "XML",
    ".yaml": "YAML",
    ".yml": "YAML",
}

LANGUAGE_BY_FILENAME = {
    "dockerfile": "Dockerfile",
    "makefile": "Makefile",
}


@dataclass(frozen=True, slots=True)
class ScannedRepositoryFile:
    path: str
    extension: str
    language: str
    size_bytes: int
    content_sha256: str


def scan_repository(root: Path, max_file_size_bytes: int) -> list[ScannedRepositoryFile]:
    """扫描适合后续 RAG 的文本文件，并生成稳定的文件元数据。"""

    root = root.resolve()
    scanned_files: list[ScannedRepositoryFile] = []

    for path in root.rglob("*"):
        relative_path = path.relative_to(root)
        # 依赖、构建产物和版本库内部文件不应进入知识库。
        if any(part.lower() in IGNORED_DIRECTORIES for part in relative_path.parts[:-1]):
            continue
        # 跳过软链接，避免扫描路径逃逸到仓库目录以外。
        if not path.is_file() or path.is_symlink():
            continue

        language = LANGUAGE_BY_FILENAME.get(path.name.lower())
        extension = path.suffix.lower()
        if language is None:
            language = LANGUAGE_BY_EXTENSION.get(extension)
        if language is None:
            continue

        size_bytes = path.stat().st_size
        # 超大文件通常是生成物或数据文件，会显著增加后续切片和 Embedding 成本。
        if size_bytes > max_file_size_bytes:
            continue

        content = path.read_bytes()
        # 文本中出现空字节通常意味着这是二进制文件。
        if b"\x00" in content[:8192]:
            continue

        scanned_files.append(
            ScannedRepositoryFile(
                path=relative_path.as_posix(),
                extension=extension or path.name.lower(),
                language=language,
                size_bytes=size_bytes,
                content_sha256=sha256(content).hexdigest(),
            )
        )

    return sorted(scanned_files, key=lambda item: item.path)
