from fastapi import APIRouter

from repopilot.api.routes import (
    chunks,
    conversations,
    diagnosis,
    evaluations,
    health,
    projects,
    rag,
    retrieval,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["system"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(
    conversations.router,
    prefix="/projects/{project_id}/conversations",
    tags=["conversations"],
)
api_router.include_router(
    chunks.router,
    prefix="/projects/{project_id}/chunks",
    tags=["chunks"],
)
api_router.include_router(
    retrieval.router,
    prefix="/projects/{project_id}/index",
    tags=["retrieval"],
)
api_router.include_router(
    rag.router,
    prefix="/projects/{project_id}/rag",
    tags=["rag"],
)
api_router.include_router(
    diagnosis.router,
    prefix="/projects/{project_id}/diagnosis",
    tags=["diagnosis"],
)
api_router.include_router(
    evaluations.router,
    prefix="/projects/{project_id}/evaluations",
    tags=["evaluations"],
)
