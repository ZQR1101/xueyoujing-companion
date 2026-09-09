"""练习端点：作答、分级提示、查看解析。"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.deps import CurrentStudent, DbSession
from app.api.dto import RequestHint, RequestSolution, SubmitAttempt
from app.api.envelope import envelope
from app.api.idempotency import run_idempotent
from app.infrastructure.repositories import learning as learning_repo
from app.services import attempts as attempts_service
from app.services import tutoring as tutoring_service

router = APIRouter(prefix="/api/v1", tags=["exercises"])


@router.get("/exercises/{exercise_id}/attempts")
def get_exercise_attempts(
    request: Request, db: DbSession, student: CurrentStudent, exercise_id: str
) -> dict:
    from sqlalchemy import select

    from app.api.envelope import envelope
    from app.infrastructure.models import Attempt

    exercise = learning_repo.exercise_owned(db, student.id, exercise_id)
    rows = list(
        db.execute(
            select(Attempt)
            .where(Attempt.exercise_id == exercise.id, Attempt.student_id == student.id)
            .order_by(Attempt.created_at, Attempt.id)
        ).scalars().all()
    )
    data = {
        "attempts": [
            {
                "id": a.id,
                "answer": a.answer,
                "grade": a.grade,
                "hint_level_at_submission": a.hint_level_at_submission,
                "created_at": a.created_at.isoformat() + "Z",
            }
            for a in rows
        ]
    }
    return envelope(request, data, resource_version=exercise.version)


@router.post("/exercises/{exercise_id}/attempts")
def submit_attempt(
    request: Request,
    db: DbSession,
    student: CurrentStudent,
    exercise_id: str,
    payload: SubmitAttempt,
) -> dict:
    def execute(session) -> tuple[dict, int | None, dict | None]:  # noqa: ANN001
        exercise = learning_repo.exercise_owned(session, student.id, exercise_id)
        return attempts_service.submit_attempt(
            session,
            student=student,
            exercise=exercise,
            answer=payload.answer,
            expected_version=payload.expected_version,
            correlation_id=getattr(request.state, "trace_id", None),
        )

    return run_idempotent(
        db,
        student_id=student.id,
        request=request,
        payload=payload.model_dump(),
        execute=execute,
    )


@router.post("/exercises/{exercise_id}/hints")
def request_hint(
    request: Request,
    db: DbSession,
    student: CurrentStudent,
    exercise_id: str,
    payload: RequestHint,
) -> dict:
    def execute(session) -> tuple[dict, int, None]:  # noqa: ANN001
        exercise = learning_repo.exercise_owned(session, student.id, exercise_id)
        result = tutoring_service.show_hint(
            session,
            student_id=student.id,
            exercise=exercise,
            expected_version=payload.expected_version,
        )
        return result, exercise.version, None

    return run_idempotent(
        db,
        student_id=student.id,
        request=request,
        payload=payload.model_dump(),
        execute=execute,
    )


@router.post("/exercises/{exercise_id}/solution")
def request_solution(
    request: Request,
    db: DbSession,
    student: CurrentStudent,
    exercise_id: str,
    payload: RequestSolution,
) -> dict:
    def execute(session) -> tuple[dict, int, None]:  # noqa: ANN001
        exercise = learning_repo.exercise_owned(session, student.id, exercise_id)
        result = tutoring_service.show_solution(
            session,
            student_id=student.id,
            exercise=exercise,
            expected_version=payload.expected_version,
        )
        return result, exercise.version, None

    return run_idempotent(
        db,
        student_id=student.id,
        request=request,
        payload=payload.model_dump(),
        execute=execute,
    )
