"""诊断评估端点：GET 状态（只读）、POST 完成（写）。"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from app.api.deps import CurrentStudent, DbSession
from app.api.dto import CompleteAssessment
from app.api.envelope import envelope
from app.api.idempotency import run_idempotent
from app.api.serializers import public_question_dto
from app.infrastructure.models import Goal, LearningSession
from app.infrastructure.repositories import goals as goals_repo
from app.infrastructure.repositories import learning as learning_repo
from app.infrastructure.repositories import questions as questions_repo
from app.services import diagnosis as diagnosis_service

router = APIRouter(prefix="/api/v1", tags=["assessments"])


def _assessment_dto(assessment) -> dict:  # noqa: ANN001
    return {
        "id": assessment.id,
        "goal_id": assessment.goal_id,
        "status": assessment.status,
        "question_ids": assessment.question_ids,
        "coverage": assessment.coverage,
        "version": assessment.version,
    }


@router.get("/assessments/{assessment_id}")
def get_assessment(
    request: Request,
    db: DbSession,
    student: CurrentStudent,
    assessment_id: str,
    after_exercise_id: str | None = Query(default=None),
) -> dict:
    assessment = learning_repo.assessment_owned(db, student.id, assessment_id)
    exercises = learning_repo.exercises_for_assessment(db, assessment)

    answered = []
    for exercise in exercises:
        attempts = learning_repo.attempts_for_exercise(db, exercise.id)
        if attempts:
            answered.append(
                {
                    "exercise_id": exercise.id,
                    "question_id": exercise.question_id,
                    "grade": attempts[-1].grade,
                }
            )

    next_exercise = diagnosis_service.next_open_exercise(
        db, assessment, after_exercise_id=after_exercise_id
    )
    question = (
        questions_repo.question_owned(db, next_exercise.question_id)
        if next_exercise is not None
        else None
    )

    data = {
        "assessment": _assessment_dto(assessment),
        "answered": answered,
        "next": {
            "exercise": {
                "id": next_exercise.id,
                "status": next_exercise.status,
                "version": next_exercise.version,
            },
            "question": public_question_dto(question),
        }
        if next_exercise is not None and question is not None
        else None,
    }
    return envelope(request, data, resource_version=assessment.version)


@router.post("/assessments/{assessment_id}/complete")
def complete_assessment(
    request: Request,
    db: DbSession,
    student: CurrentStudent,
    assessment_id: str,
    payload: CompleteAssessment,
) -> dict:
    def execute(session) -> tuple[dict, int, None]:  # noqa: ANN001
        assessment = learning_repo.assessment_owned(session, student.id, assessment_id)
        goal: Goal = goals_repo.goal_owned(session, student.id, assessment.goal_id)
        learning_session = learning_repo.session_for_goal(session, student.id, goal.id)
        if learning_session is None:
            from app.domain.errors import IllegalState

            raise IllegalState("该目标没有学习会话")
        result = diagnosis_service.complete_assessment(
            session,
            student=student,
            session=learning_session,
            goal=goal,
            assessment=assessment,
            expected_version=payload.expected_version,
            correlation_id=getattr(request.state, "trace_id", None),
        )
        return result, assessment.version, None

    return run_idempotent(
        db,
        student_id=student.id,
        request=request,
        payload=payload.model_dump(),
        execute=execute,
    )
