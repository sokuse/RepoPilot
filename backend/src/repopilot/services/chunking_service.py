import ast
import hashlib
import re
from dataclasses import dataclass, field

from langchain_text_splitters import Language, RecursiveCharacterTextSplitter
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from repopilot.core.config import settings
from repopilot.models.knowledge_chunk import KnowledgeChunk
from repopilot.models.project import Project
from repopilot.models.repository_file import RepositoryFile
from repopilot.models.vector_index_state import VectorIndexState
from repopilot.schemas.chunk import ChunkingStatsResponse, KnowledgeChunkResponse

MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

# LangChain 针对这些语言提供了更合理的分隔符顺序，例如优先在类、函数边界处切分。
LANGCHAIN_LANGUAGES: dict[str, Language] = {
    "python": Language.PYTHON,
    "javascript": Language.JS,
    "typescript": Language.TS,
    "java": Language.JAVA,
    "c": Language.C,
    "c++": Language.CPP,
    "c#": Language.CSHARP,
    "go": Language.GO,
    "rust": Language.RUST,
    "php": Language.PHP,
    "ruby": Language.RUBY,
    "html": Language.HTML,
    "markdown": Language.MARKDOWN,
}


@dataclass(slots=True)
class ChunkDraft:
    content: str
    start_line: int
    end_line: int
    strategy: str
    symbol_name: str | None = None
    extra_metadata: dict[str, object] = field(default_factory=dict)


def _split_recursively(
    text: str,
    *,
    base_line: int,
    strategy: str,
    language: Language | None = None,
    symbol_name: str | None = None,
    extra_metadata: dict[str, object] | None = None,
) -> list[ChunkDraft]:
    if not text.strip():
        return []

    splitter_options = {
        "chunk_size": settings.chunk_size_chars,
        "chunk_overlap": settings.chunk_overlap_chars,
        "add_start_index": True,
    }
    splitter = (
        RecursiveCharacterTextSplitter.from_language(language=language, **splitter_options)
        if language is not None
        else RecursiveCharacterTextSplitter(**splitter_options)
    )

    drafts: list[ChunkDraft] = []
    for document in splitter.create_documents([text]):
        content = document.page_content
        start_index = int(document.metadata.get("start_index", 0))
        start_line = base_line + text[:start_index].count("\n")
        end_line = start_line + content.count("\n")
        drafts.append(
            ChunkDraft(
                content=content,
                start_line=start_line,
                end_line=end_line,
                strategy=strategy,
                symbol_name=symbol_name,
                extra_metadata=extra_metadata or {},
            )
        )
    return drafts


def split_python(text: str) -> list[ChunkDraft]:
    """优先按 Python 顶层类/函数切片；语法不完整时安全降级为递归切片。"""

    try:
        tree = ast.parse(text)
    except SyntaxError:
        return _split_recursively(
            text,
            base_line=1,
            strategy="code_recursive",
            language=Language.PYTHON,
            extra_metadata={"fallback_reason": "syntax_error"},
        )

    lines = text.splitlines(keepends=True)
    nodes = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    if not nodes:
        return _split_recursively(
            text, base_line=1, strategy="code_recursive", language=Language.PYTHON
        )

    drafts: list[ChunkDraft] = []
    next_line = 1
    for node in nodes:
        decorator_lines = [item.lineno for item in node.decorator_list]
        node_start = min([node.lineno, *decorator_lines])
        node_end = node.end_lineno or node.lineno

        if node_start > next_line:
            drafts.extend(
                _split_recursively(
                    "".join(lines[next_line - 1 : node_start - 1]),
                    base_line=next_line,
                    strategy="python_module",
                    language=Language.PYTHON,
                )
            )

        drafts.extend(
            _split_recursively(
                "".join(lines[node_start - 1 : node_end]),
                base_line=node_start,
                strategy="python_ast",
                language=Language.PYTHON,
                symbol_name=node.name,
                extra_metadata={"symbol_type": type(node).__name__},
            )
        )
        next_line = node_end + 1

    if next_line <= len(lines):
        drafts.extend(
            _split_recursively(
                "".join(lines[next_line - 1 :]),
                base_line=next_line,
                strategy="python_module",
                language=Language.PYTHON,
            )
        )
    return drafts


def split_markdown(text: str) -> list[ChunkDraft]:
    """按 Markdown 标题建立章节，再对过长章节递归切分并保留标题路径。"""

    lines = text.splitlines(keepends=True)
    headings: list[tuple[int, int, str]] = []
    for line_number, line in enumerate(lines, start=1):
        match = MARKDOWN_HEADING.match(line.rstrip("\r\n"))
        if match:
            headings.append((line_number, len(match.group(1)), match.group(2)))

    if not headings:
        return _split_recursively(text, base_line=1, strategy="text_recursive")

    drafts: list[ChunkDraft] = []
    if headings[0][0] > 1:
        drafts.extend(
            _split_recursively(
                "".join(lines[: headings[0][0] - 1]),
                base_line=1,
                strategy="markdown_header",
            )
        )

    header_stack: list[tuple[int, str]] = []
    for index, (start_line, level, title) in enumerate(headings):
        header_stack = [
            (item_level, item)
            for item_level, item in header_stack
            if item_level < level
        ]
        header_stack.append((level, title))
        end_line = headings[index + 1][0] - 1 if index + 1 < len(headings) else len(lines)
        header_path = " > ".join(item for _, item in header_stack)
        drafts.extend(
            _split_recursively(
                "".join(lines[start_line - 1 : end_line]),
                base_line=start_line,
                strategy="markdown_header",
                language=Language.MARKDOWN,
                symbol_name=header_path,
                extra_metadata={"heading_level": level},
            )
        )
    return drafts


def split_content(text: str, language: str) -> list[ChunkDraft]:
    normalized_language = language.lower()
    if normalized_language == "python":
        return split_python(text)
    if normalized_language == "markdown":
        return split_markdown(text)
    langchain_language = LANGCHAIN_LANGUAGES.get(normalized_language)
    return _split_recursively(
        text,
        base_line=1,
        strategy="code_recursive" if langchain_language else "text_recursive",
        language=langchain_language,
    )


class ChunkingService:
    @staticmethod
    def rebuild(session: Session, project: Project) -> ChunkingStatsResponse:
        repository_root = (settings.repository_storage_path / project.id).resolve()
        files = session.scalars(
            select(RepositoryFile)
            .where(RepositoryFile.project_id == project.id)
            .order_by(RepositoryFile.path)
        ).all()

        # Chunk 属于可重复生成的派生数据，重建时先清理旧结果，防止内容更新后残留脏数据。
        session.execute(delete(KnowledgeChunk).where(KnowledgeChunk.project_id == project.id))
        # 切片内容变化后旧向量不可再被使用，必须显式重新构建索引。
        session.execute(
            delete(VectorIndexState).where(VectorIndexState.project_id == project.id)
        )
        for repository_file in files:
            source_path = (repository_root / repository_file.path).resolve()
            if not source_path.is_relative_to(repository_root) or not source_path.is_file():
                continue
            content = source_path.read_text(encoding="utf-8", errors="replace")
            for chunk_index, draft in enumerate(
                split_content(content, repository_file.language)
            ):
                session.add(
                    KnowledgeChunk(
                        project_id=project.id,
                        repository_file_id=repository_file.id,
                        chunk_index=chunk_index,
                        strategy=draft.strategy,
                        content=draft.content,
                        content_sha256=hashlib.sha256(draft.content.encode()).hexdigest(),
                        char_count=len(draft.content),
                        start_line=draft.start_line,
                        end_line=draft.end_line,
                        symbol_name=draft.symbol_name,
                        extra_metadata=draft.extra_metadata,
                    )
                )
        session.commit()
        return ChunkingService.stats(session, project.id)

    @staticmethod
    def stats(session: Session, project_id: str) -> ChunkingStatsResponse:
        total_chunks, total_chars = session.execute(
            select(
                func.count(KnowledgeChunk.id),
                func.coalesce(func.sum(KnowledgeChunk.char_count), 0),
            )
            .where(KnowledgeChunk.project_id == project_id)
        ).one()
        strategy_rows = session.execute(
            select(KnowledgeChunk.strategy, func.count(KnowledgeChunk.id))
            .where(KnowledgeChunk.project_id == project_id)
            .group_by(KnowledgeChunk.strategy)
            .order_by(KnowledgeChunk.strategy)
        ).all()
        return ChunkingStatsResponse(
            project_id=project_id,
            total_chunks=total_chunks,
            total_chars=total_chars,
            strategy_breakdown=dict(strategy_rows),
        )

    @staticmethod
    def list(
        session: Session, project_id: str, offset: int, limit: int
    ) -> list[KnowledgeChunkResponse]:
        rows = session.execute(
            select(KnowledgeChunk, RepositoryFile.path)
            .join(RepositoryFile, RepositoryFile.id == KnowledgeChunk.repository_file_id)
            .where(KnowledgeChunk.project_id == project_id)
            .order_by(RepositoryFile.path, KnowledgeChunk.chunk_index)
            .offset(offset)
            .limit(limit)
        ).all()
        return [
            KnowledgeChunkResponse(source_path=source_path, **chunk.__dict__)
            for chunk, source_path in rows
        ]


chunking_service = ChunkingService()
