from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from repopilot.models.project import Project
from repopilot.schemas.project import ProjectCreate


class DuplicateRepositoryError(Exception):
    """Raised when a repository has already been registered."""


class ProjectService:
    @staticmethod
    def list(session: Session) -> list[Project]:
        statement = select(Project).order_by(Project.created_at.desc())
        return list(session.scalars(statement).all())

    @staticmethod
    def get(session: Session, project_id: str) -> Project | None:
        return session.get(Project, project_id)

    @staticmethod
    def create(session: Session, payload: ProjectCreate) -> Project:
        repository_url = str(payload.repository_url).rstrip("/")
        if repository_url.endswith(".git"):
            repository_url = repository_url[:-4]

        project = Project(
            name=payload.name,
            repository_url=repository_url,
            default_branch=payload.default_branch,
        )
        session.add(project)
        try:
            session.commit()
        except IntegrityError as error:
            session.rollback()
            raise DuplicateRepositoryError from error
        session.refresh(project)
        return project

    @staticmethod
    def delete(session: Session, project: Project) -> None:
        session.delete(project)
        session.commit()


project_service = ProjectService()
