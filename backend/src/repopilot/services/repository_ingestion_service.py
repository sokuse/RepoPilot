import logging
import os
import shutil
import subprocess
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from repopilot.core.config import settings
from repopilot.db.session import SessionLocal
from repopilot.models.project import Project
from repopilot.models.repository_file import RepositoryFile
from repopilot.schemas.ingestion import RepositoryStatsResponse
from repopilot.services.repository_scanner import ScannedRepositoryFile, scan_repository

logger = logging.getLogger(__name__)


class RepositoryCloneError(RuntimeError):
    """Git 无法完成仓库克隆时抛出的业务异常。"""


class RepositoryIngestionService:
    @staticmethod
    def start(session: Session, project: Project) -> Project:
        project.status = "indexing"
        session.commit()
        session.refresh(project)
        return project

    @staticmethod
    def stats(session: Session, project_id: str) -> RepositoryStatsResponse:
        total_files, total_bytes = session.execute(
            select(
                func.count(RepositoryFile.id),
                func.coalesce(func.sum(RepositoryFile.size_bytes), 0),
            ).where(RepositoryFile.project_id == project_id)
        ).one()
        language_rows = session.execute(
            select(RepositoryFile.language, func.count(RepositoryFile.id))
            .where(RepositoryFile.project_id == project_id)
            .group_by(RepositoryFile.language)
            .order_by(func.count(RepositoryFile.id).desc())
        ).all()
        return RepositoryStatsResponse(
            project_id=project_id,
            total_files=total_files,
            total_bytes=total_bytes,
            language_breakdown=dict(language_rows),
        )

    @staticmethod
    def replace_files(
        session: Session, project: Project, scanned_files: list[ScannedRepositoryFile]
    ) -> None:
        # 同一个项目再次采集时，用新扫描结果整体替换旧文件清单。
        session.execute(
            delete(RepositoryFile).where(RepositoryFile.project_id == project.id)
        )
        session.add_all(
            [
                RepositoryFile(
                    project_id=project.id,
                    path=file.path,
                    extension=file.extension,
                    language=file.language,
                    size_bytes=file.size_bytes,
                    content_sha256=file.content_sha256,
                )
                for file in scanned_files
            ]
        )
        project.status = "ready"
        session.commit()


def _repository_target(project_id: str) -> Path:
    storage_root = settings.repository_storage_path.resolve()
    target = (storage_root / project_id).resolve()
    # 项目 ID 最终必须落在配置的仓库存储目录下一层，防止路径穿越。
    if target.parent != storage_root:
        raise ValueError("Repository target escaped the configured storage directory")
    return target


def _remove_existing_target(target: Path) -> None:
    storage_root = settings.repository_storage_path.resolve()
    if target.parent != storage_root:
        raise ValueError("Refusing to remove a path outside repository storage")
    if target.exists():
        shutil.rmtree(target)


def remove_repository_checkout(project_id: str) -> None:
    """删除项目时同步清理受控目录内的本地仓库副本。"""

    _remove_existing_target(_repository_target(project_id))


def clone_repository(repository_url: str, branch: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    _remove_existing_target(target)
    environment = os.environ.copy()
    environment["GIT_TERMINAL_PROMPT"] = "0"
    # 不使用 shell=True；URL 和分支作为独立参数传入，避免命令拼接注入。
    # depth=1 只下载目标分支最新快照，采集阶段不需要完整 Git 历史。
    command = [
        "git",
        "clone",
        "--depth=1",
        "--single-branch",
        "--no-tags",
        "--branch",
        branch,
        "--",
        repository_url,
        str(target),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            timeout=settings.git_clone_timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        _remove_existing_target(target)
        raise RepositoryCloneError("Git clone could not be completed") from error

    if result.returncode != 0:
        _remove_existing_target(target)
        message = result.stderr.strip()[-1000:] or "Unknown Git clone error"
        raise RepositoryCloneError(message)


def run_repository_ingestion(project_id: str) -> None:
    # 后台任务发生在原 HTTP 请求之后，因此必须创建自己的数据库 Session。
    with SessionLocal() as session:
        project = session.get(Project, project_id)
        if project is None:
            return

        try:
            target = _repository_target(project.id)
            clone_repository(project.repository_url, project.default_branch, target)
            scanned_files = scan_repository(target, settings.max_scanned_file_size_bytes)
            RepositoryIngestionService.replace_files(session, project, scanned_files)
        except Exception:
            session.rollback()
            project = session.get(Project, project_id)
            if project is not None:
                project.status = "failed"
                session.commit()
            logger.exception("Repository ingestion failed for project %s", project_id)


repository_ingestion_service = RepositoryIngestionService()
