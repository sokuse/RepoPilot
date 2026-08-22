from fastapi import APIRouter

from repopilot.api.routes import chunks, health, projects

api_router = APIRouter()
api_router.include_router(health.router, tags=["system"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(
    chunks.router,
    prefix="/projects/{project_id}/chunks",
    tags=["chunks"],
)
