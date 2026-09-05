from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status

from repopilot.db.session import SessionDep
from repopilot.schemas.evaluation import (
    EvaluationCaseCreate,
    EvaluationCaseResponse,
    EvaluationRunCreate,
    EvaluationRunDetail,
    EvaluationRunSummary,
)
from repopilot.services.evaluation_service import (
    InvalidExpectedFilesError,
    evaluation_service,
)
from repopilot.services.project_service import project_service

router = APIRouter()


def _ready_project(project_id: UUID, session: SessionDep):
    project = project_service.get(session, str(project_id))
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.status != "ready":
        raise HTTPException(status_code=409, detail="Repository must be ready before evaluation")
    return project


@router.post("/cases", response_model=EvaluationCaseResponse, status_code=201)
def create_evaluation_case(
    project_id: UUID, payload: EvaluationCaseCreate, session: SessionDep
) -> EvaluationCaseResponse:
    project = _ready_project(project_id, session)
    try:
        case = evaluation_service.create_case(session, project.id, payload)
    except InvalidExpectedFilesError as error:
        missing = "、".join(error.missing_files)
        raise HTTPException(
            status_code=422,
            detail=f"期望文件不在当前仓库扫描清单中：{missing}",
        ) from error
    return EvaluationCaseResponse.model_validate(case)


@router.get("/cases", response_model=list[EvaluationCaseResponse])
def list_evaluation_cases(
    project_id: UUID, session: SessionDep
) -> list[EvaluationCaseResponse]:
    project = _ready_project(project_id, session)
    return [
        EvaluationCaseResponse.model_validate(case)
        for case in evaluation_service.list_cases(session, project.id)
    ]


@router.delete("/cases/{case_id}", status_code=204)
def delete_evaluation_case(
    project_id: UUID, case_id: UUID, session: SessionDep
) -> Response:
    project = _ready_project(project_id, session)
    if not evaluation_service.delete_case(session, project.id, str(case_id)):
        raise HTTPException(status_code=404, detail="Evaluation case not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/runs", response_model=EvaluationRunDetail, status_code=201)
def run_evaluation(
    project_id: UUID, payload: EvaluationRunCreate, session: SessionDep
) -> EvaluationRunDetail:
    project = _ready_project(project_id, session)
    try:
        return evaluation_service.run(session, project.id, payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail="Please select at least one case") from error


@router.get("/runs", response_model=list[EvaluationRunSummary])
def list_evaluation_runs(
    project_id: UUID, session: SessionDep
) -> list[EvaluationRunSummary]:
    project = _ready_project(project_id, session)
    return evaluation_service.list_runs(session, project.id)


@router.delete("/runs/{run_id}", status_code=204)
def delete_evaluation_run(
    project_id: UUID, run_id: UUID, session: SessionDep
) -> Response:
    project = _ready_project(project_id, session)
    if not evaluation_service.delete_run(session, project.id, str(run_id)):
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/runs/{run_id}", response_model=EvaluationRunDetail)
def get_evaluation_run(
    project_id: UUID, run_id: UUID, session: SessionDep
) -> EvaluationRunDetail:
    project = _ready_project(project_id, session)
    run = evaluation_service.get_run(session, project.id, str(run_id))
    if run is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    return run
