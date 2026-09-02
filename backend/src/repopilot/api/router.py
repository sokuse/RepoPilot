from fastapi import APIRouter

from repopilot.api.routes import chunks, diagnosis, health, projects, rag, retrieval

api_router = APIRouter()
api_router.include_router(health.router, tags=["system"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
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
