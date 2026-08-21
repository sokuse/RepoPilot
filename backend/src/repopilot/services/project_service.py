from datetime import UTC, datetime
from threading import Lock
from uuid import uuid4

from repopilot.schemas.project import ProjectCreate, ProjectResponse


class ProjectService:
    """Temporary in-memory project store, replaced by PostgreSQL in phase two."""

    def __init__(self) -> None:
        self._projects: list[ProjectResponse] = []
        self._lock = Lock()

    def list(self) -> list[ProjectResponse]:
        with self._lock:
            return list(self._projects)

    def create(self, payload: ProjectCreate) -> ProjectResponse:
        project = ProjectResponse(
            id=uuid4(),
            name=payload.name,
            repository_url=str(payload.repository_url),
            default_branch=payload.default_branch,
            status="pending",
            created_at=datetime.now(UTC),
        )
        with self._lock:
            self._projects.insert(0, project)
        return project


project_service = ProjectService()

