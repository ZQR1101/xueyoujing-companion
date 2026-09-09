"""T10-B AI 学情诊断端点。

- POST /goals/{goal_id}/diagnosis-report：生成并持久化（幂等）；
- GET  /goals/{goal_id}/diagnosis-report：读取最近一次（只读，零写入）。
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.deps import CurrentStudent, DbSession
from app.api.dto import GenerateDiagnosisReport
from app.api.envelope import envelope
from app.api.idempotency import run_idempotent
from app.domain.errors import ResourceNotFound
from app.infrastructure.repositories import goals as goals_repo
from app.services import diagnosis_report as report_service

router = APIRouter(prefix="/api/v1", tags=["diagnosis-report"])


@router.post("/goals/{goal_id}/diagnosis-report")
def create_diagnosis_report(
    request: Request,
    db: DbSession,
    student: CurrentStudent,
    goal_id: str,
    payload: GenerateDiagnosisReport | None = None,
) -> dict:
    body = payload.model_dump() if payload is not None else {}

    def execute(session) -> tuple[dict, int, None]:  # noqa: ANN001
        goal = goals_repo.goal_owned(session, student.id, goal_id)
        data, report = report_service.generate_report(
            session,
            student=student,
            goal=goal,
            correlation_id=getattr(request.state, "trace_id", None),
        )
        return data, report.duration_ms, None

    return run_idempotent(
        db,
        student_id=student.id,
        request=request,
        payload={"goal_id": goal_id, **body},
        execute=execute,
    )


@router.get("/goals/{goal_id}/diagnosis-report")
def get_diagnosis_report(
    request: Request, db: DbSession, student: CurrentStudent, goal_id: str
) -> dict:
    goal = goals_repo.goal_owned(db, student.id, goal_id)
    report = report_service.latest_report(db, student.id, goal.id)
    if report is None:
        raise ResourceNotFound("尚未生成学情诊断")
    data = {
        "report_id": report.id,
        "status": report.status,
        "planner_source": report.planner_source,
        "model_id": report.model_id,
        "fallback_reason": report.fallback_reason,
        "summary": report.summary,
        "observations": report.observations,
        "hypotheses": report.hypotheses,
        "recommended_probe": report.recommended_probe,
        "evidence_ids": report.evidence_ids,
        "policy_version": report.input_state.get("policy_version"),
        "duration_ms": report.duration_ms,
        "created_at": report.created_at.isoformat() + "Z",
    }
    return envelope(request, data, resource_version=None)
