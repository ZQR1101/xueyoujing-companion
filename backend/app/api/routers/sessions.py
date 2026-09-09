"""学习会话端点：诊断、会话状态、任务启动、暂停/恢复。"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.deps import CurrentStudent, DbSession
from app.api.dto import PauseSession, ResumeSession, StartDiagnosis, StartNextTask
from app.api.envelope import envelope
from app.api.idempotency import run_idempotent
from app.api.serializers import public_question_dto, session_dto
from app.domain.enums import AssessmentStatus, EventType, ExerciseStatus, SessionStatus, TaskStatus
from app.domain.errors import IllegalState, VersionConflict
from app.infrastructure.models import Exercise, Goal, LearningSession
from app.infrastructure.repositories import events as events_repo
from app.infrastructure.repositories import goals as goals_repo
from app.infrastructure.repositories import learning as learning_repo
from app.infrastructure.repositories import plans as plans_repo
from app.infrastructure.repositories import questions as questions_repo
from app.services import diagnosis as diagnosis_service
from app.services import tutoring as tutoring_service

router = APIRouter(prefix="/api/v1", tags=["sessions"])


def _exercise_brief(exercise) -> dict:  # noqa: ANN001
    return {
        "id": exercise.id,
        "question_id": exercise.question_id,
        "status": exercise.status,
        "version": exercise.version,
    }


@router.post("/sessions/{session_id}/diagnosis")
def start_diagnosis(
    request: Request, db: DbSession, student: CurrentStudent, session_id: str, payload: StartDiagnosis
) -> dict:
    def execute(session) -> tuple[dict, int, None]:  # noqa: ANN001
        learning_session = learning_repo.session_owned(session, student.id, session_id)
        goal = goals_repo.goal_owned(session, student.id, learning_session.goal_id)
        assessment, first_exercise = diagnosis_service.start_diagnosis(
            session,
            student=student,
            session=learning_session,
            goal=goal,
            expected_version=payload.expected_version,
            correlation_id=getattr(request.state, "trace_id", None),
        )
        question = (
            questions_repo.question_owned(session, first_exercise.question_id)
            if first_exercise is not None
            else None
        )
        data = {
            "assessment": {
                "id": assessment.id,
                "status": assessment.status,
                "question_ids": assessment.question_ids,
                "coverage": assessment.coverage,
                "version": assessment.version,
            },
            "exercise": _exercise_brief(first_exercise) if first_exercise else None,
            "question": public_question_dto(question) if question else None,
            "session": session_dto(learning_session),
        }
        return data, assessment.version, None

    return run_idempotent(
        db,
        student_id=student.id,
        request=request,
        payload=payload.model_dump(),
        execute=execute,
    )


@router.get("/sessions/{session_id}")
def get_session(
    request: Request, db: DbSession, student: CurrentStudent, session_id: str
) -> dict:
    learning_session: LearningSession = learning_repo.session_owned(db, student.id, session_id)
    goal: Goal = goals_repo.goal_owned(db, student.id, learning_session.goal_id)

    resumable = None
    if learning_session.status != SessionStatus.completed.value:
        assessment = learning_repo.in_progress_assessment_for_goal(db, student.id, goal.id)
        if assessment is not None:
            next_exercise = diagnosis_service.next_open_exercise(db, assessment)
            question = (
                questions_repo.question_owned(db, next_exercise.question_id)
                if next_exercise is not None
                else None
            )
            resumable = {
                "kind": "diagnosis",
                "assessment": {
                    "id": assessment.id,
                    "status": assessment.status,
                    "question_ids": assessment.question_ids,
                    "version": assessment.version,
                },
                "exercise": _exercise_brief(next_exercise) if next_exercise else None,
                "question": public_question_dto(question) if question else None,
            }
        else:
            open_exercise = db.execute(
                _open_task_exercise_query(student.id, goal.id)
            ).scalar_one_or_none()
            if open_exercise is not None:
                question = questions_repo.question_owned(db, open_exercise.question_id)
                resumable = {
                    "kind": "learning",
                    "exercise": {
                        "id": open_exercise.id,
                        "status": open_exercise.status,
                        "version": open_exercise.version,
                        "hint_level": open_exercise.hint_level,
                        "solution_seen": open_exercise.solution_seen,
                    },
                    "question": public_question_dto(question),
                }

    data = {
        "session": session_dto(learning_session),
        "goal": {"id": goal.id, "course_id": goal.course_id, "status": goal.status},
        "resumable": resumable,
    }
    return envelope(request, data, resource_version=learning_session.version)


def _open_task_exercise_query(student_id: str, goal_id: str):
    from sqlalchemy import select

    return (
        select(Exercise)
        .join(LearningSession, LearningSession.goal_id == goal_id)
        .where(
            Exercise.student_id == student_id,
            Exercise.task_id.isnot(None),
            Exercise.status == ExerciseStatus.open.value,
        )
        .order_by(Exercise.created_at)
        .limit(1)
    )


@router.post("/sessions/{session_id}/start-next")
def start_next(
    request: Request, db: DbSession, student: CurrentStudent, session_id: str, payload: StartNextTask
) -> dict:
    def execute(session) -> tuple[dict, int, dict | None]:  # noqa: ANN001
        learning_session = learning_repo.session_owned(session, student.id, session_id)
        goal = goals_repo.goal_owned(session, student.id, learning_session.goal_id)
        return tutoring_service.start_next(
            session,
            student=student,
            session=learning_session,
            goal=goal,
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


@router.post("/sessions/{session_id}/pause")
def pause_session(
    request: Request, db: DbSession, student: CurrentStudent, session_id: str, payload: PauseSession
) -> dict:
    def execute(session) -> tuple[dict, int, None]:  # noqa: ANN001
        learning_session = learning_repo.session_owned(session, student.id, session_id)
        if payload.expected_version != learning_session.version:
            raise VersionConflict("学习状态已更新，请刷新后继续")
        if learning_session.status == SessionStatus.completed.value:
            raise IllegalState("会话已结束，不能再暂停")
        if learning_session.status == SessionStatus.paused.value:
            raise IllegalState("会话已处于暂停状态")

        open_exercise = session.execute(
            _open_task_exercise_query(student.id, learning_session.goal_id)
        ).scalar_one_or_none()
        events_repo.record_event(
            session,
            student_id=student.id,
            session_id=learning_session.id,
            type=EventType.session_paused,
            payload={
                "previous_status": learning_session.status,
                "open_exercise_id": open_exercise.id if open_exercise else None,
            },
            correlation_id=getattr(request.state, "trace_id", None),
        )
        learning_repo.bump_learning_session_version(
            session, learning_session.id, learning_session.version
        )
        session.refresh(learning_session)
        learning_session.status = SessionStatus.paused.value
        data = {
            "session": session_dto(learning_session),
            "resume_hint": "调用 resume 恢复；未关闭练习与提示等级已保存。",
        }
        return data, learning_session.version, None

    return run_idempotent(
        db,
        student_id=student.id,
        request=request,
        payload=payload.model_dump(),
        execute=execute,
    )


@router.post("/sessions/{session_id}/resume")
def resume_session(
    request: Request, db: DbSession, student: CurrentStudent, session_id: str, payload: ResumeSession
) -> dict:
    def execute(session) -> tuple[dict, int, dict | None]:  # noqa: ANN001
        learning_session = learning_repo.session_owned(session, student.id, session_id)
        if payload.expected_version != learning_session.version:
            raise VersionConflict("学习状态已更新，请刷新后继续")
        if learning_session.status == SessionStatus.completed.value:
            raise IllegalState("会话已结束，无需恢复")
        if learning_session.status != SessionStatus.paused.value:
            raise IllegalState("会话未处于暂停状态")

        goal = goals_repo.goal_owned(session, student.id, learning_session.goal_id)
        assessment = learning_repo.in_progress_assessment_for_goal(
            session, student.id, goal.id
        )
        open_exercise = session.execute(
            _open_task_exercise_query(student.id, goal.id)
        ).scalar_one_or_none()

        if assessment is not None:
            derived = SessionStatus.diagnosing.value
        elif open_exercise is not None:
            derived = SessionStatus.learning.value
        else:
            derived = SessionStatus.ready.value

        learning_repo.bump_learning_session_version(
            session, learning_session.id, learning_session.version
        )
        session.refresh(learning_session)
        learning_session.status = derived

        resume_location = None
        if open_exercise is not None:
            question = questions_repo.question_owned(session, open_exercise.question_id)
            resume_location = {
                "kind": "learning",
                "exercise": {
                    "id": open_exercise.id,
                    "version": open_exercise.version,
                    "hint_level": open_exercise.hint_level,
                    "solution_seen": open_exercise.solution_seen,
                },
                "question": public_question_dto(question),
            }
        elif assessment is not None:
            resume_location = {"kind": "diagnosis", "assessment_id": assessment.id}

        data = {
            "session": session_dto(learning_session),
            "resume_location": resume_location,
        }
        return data, learning_session.version, None

    return run_idempotent(
        db,
        student_id=student.id,
        request=request,
        payload=payload.model_dump(),
        execute=execute,
    )
