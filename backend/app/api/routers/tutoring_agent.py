"""T12-B Tutor Agent 启发式辅导端点。

- POST /exercises/{id}/thinking：提交思路 → 结构化分析（幂等）；
- GET  /exercises/{id}/tutoring-trace：作答与辅导轨迹时间线（只读零写入）。
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.deps import CurrentStudent, DbSession
from app.api.dto import SubmitThinking
from app.api.envelope import envelope
from app.api.idempotency import run_idempotent
from app.infrastructure.repositories import learning as learning_repo
from app.services import tutoring_agent as agent_service

router = APIRouter(prefix="/api/v1", tags=["tutor-agent"])


@router.post("/exercises/{exercise_id}/thinking")
def submit_thinking(
    request: Request,
    db: DbSession,
    student: CurrentStudent,
    exercise_id: str,
    payload: SubmitThinking,
) -> dict:
    def execute(session) -> tuple[dict, int | None, None]:  # noqa: ANN001
        exercise = learning_repo.exercise_owned(session, student.id, exercise_id)
        data = agent_service.submit_thinking(
            session,
            student=student,
            exercise=exercise,
            text=payload.text,
            correlation_id=getattr(request.state, "trace_id", None),
        )
        return data, exercise.version, None

    return run_idempotent(
        db,
        student_id=student.id,
        request=request,
        payload=payload.model_dump(),
        execute=execute,
    )


@router.get("/exercises/{exercise_id}/tutoring-trace")
def get_tutoring_trace(
    request: Request, db: DbSession, student: CurrentStudent, exercise_id: str
) -> dict:
    exercise = learning_repo.exercise_owned(db, student.id, exercise_id)
    data = agent_service.tutoring_trace(db, student=student, exercise=exercise)
    latest = agent_service.latest_feedback(db, student.id, exercise_id)
    if latest is not None:
        data["latest_feedback"] = {
            "feedback": latest.payload.get("feedback"),
            "possible_problem": latest.payload.get("possible_problem"),
            "socratic_question": latest.payload.get("socratic_question"),
            "planner_source": latest.payload.get("planner_source"),
            "model_id": latest.payload.get("model_id"),
        }
    return envelope(request, data, resource_version=exercise.version)
