"""Agent 端点（§12）：messages、decisions、reflection。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.api.deps import CurrentStudent, DbSession
from app.api.dto import SaveReflection, SendMessage
from app.api.envelope import envelope
from app.api.idempotency import run_idempotent
from app.domain.errors import ResourceNotFound
from app.infrastructure.models import Decision, Evidence, Event, Exercise, Goal, LearningSession, Task
from app.infrastructure.repositories import events as events_repo
from app.infrastructure.repositories import goals as goals_repo
from app.infrastructure.repositories import learning as learning_repo
from app.services import coordinator as coordinator_service
from app.services import memory as memory_service

router = APIRouter(prefix="/api/v1", tags=["agent"])


@router.get("/sessions/{session_id}/summary-metrics")
def summary_metrics(
    request: Request, db: DbSession, student: CurrentStudent, session_id: str
) -> dict:
    """Return counters calculated from this session's persisted learning events."""
    learning_session = learning_repo.session_owned(db, student.id, session_id)
    events = list(
        db.execute(
            select(Event)
            .where(Event.student_id == student.id, Event.session_id == session_id)
            .order_by(Event.created_at, Event.id)
        ).scalars()
    )
    # Evidence has no session_id.  Its answer_graded event is the authoritative
    # connection to a session, so only attempt ids found in these events count.
    attempt_ids = {
        payload.get("attempt_id")
        for event in events
        if event.type in {"answer_submitted", "answer_graded"}
        for payload in [event.payload or {}]
        if isinstance(payload.get("attempt_id"), str)
    }
    exercise_ids = {
        payload.get("exercise_id")
        for event in events
        if event.type in {"answer_submitted", "answer_graded"}
        for payload in [event.payload or {}]
        if isinstance(payload.get("exercise_id"), str)
    }
    eligible_evidence = [] if not attempt_ids else list(
        db.execute(
            select(Evidence).where(
                Evidence.student_id == student.id,
                Evidence.attempt_id.in_(attempt_ids),
                Evidence.eligible.is_(True),
            )
        ).scalars()
    )
    completed_task_ids = {
        payload.get("task_id")
        for event in events
        if event.type == "task_completed"
        for payload in [event.payload or {}]
        if isinstance(payload.get("task_id"), str)
    }
    # Older completion events did not retain a session_id.  For task attempts,
    # recover that association from the session-scoped exercise event and only
    # count tasks whose persisted status is actually completed.
    if exercise_ids:
        attempted_task_ids = list(db.execute(
            select(Exercise.task_id).where(
                Exercise.student_id == student.id,
                Exercise.id.in_(exercise_ids),
                Exercise.task_id.is_not(None),
            )
        ).scalars())
        completed_task_ids.update(
            db.execute(
                select(Task.id).where(
                    Task.student_id == student.id,
                    Task.id.in_(attempted_task_ids),
                    Task.status == "completed",
                )
            ).scalars()
        )
    # Do not count idle time between creating a session and starting to study.
    study_seconds = int((events[-1].created_at - events[0].created_at).total_seconds()) if len(events) > 1 else 0
    return envelope(
        request,
        {
            "study_seconds": max(study_seconds, 0),
            "completed_task_count": len(completed_task_ids),
            "independent_answer_count": len(eligible_evidence),
            "new_eligible_evidence_count": len(eligible_evidence),
        },
        resource_version=learning_session.version,
    )


@router.post("/sessions/{session_id}/messages")
def send_message(
    request: Request,
    db: DbSession,
    student: CurrentStudent,
    session_id: str,
    payload: SendMessage,
) -> dict:
    def execute(session) -> tuple[dict, int, dict | None]:  # noqa: ANN001
        learning_session = learning_repo.session_owned(session, student.id, session_id)
        goal = goals_repo.goal_owned(session, student.id, learning_session.goal_id)
        return coordinator_service.send_message(
            session,
            student=student,
            session=learning_session,
            goal=goal,
            text=payload.text,
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


@router.get("/sessions/{session_id}/reflections")
def get_reflections(
    request: Request, db: DbSession, student: CurrentStudent, session_id: str
) -> dict:
    learning_session = learning_repo.session_owned(db, student.id, session_id)
    rows = list(
        db.execute(
            select(Event)
            .where(
                Event.student_id == student.id,
                Event.session_id == learning_session.id,
                Event.type == "reflection_saved",
            )
            .order_by(Event.created_at.desc())
        ).scalars().all()
    )
    data = {
        "reflections": [
            {
                "text": (r.payload or {}).get("text", ""),
                "summary": (r.payload or {}).get("summary"),
                "created_at": r.created_at.isoformat() + "Z",
            }
            for r in rows
        ]
    }
    return envelope(request, data, resource_version=learning_session.version)


@router.get("/sessions/{session_id}/decisions")
def get_decisions(
    request: Request, db: DbSession, student: CurrentStudent, session_id: str
) -> dict:
    learning_session = learning_repo.session_owned(db, student.id, session_id)
    rows = list(
        db.execute(
            select(Decision)
            .where(
                Decision.student_id == student.id,
                Decision.session_id == learning_session.id,
            )
            .order_by(Decision.created_at, Decision.id)
        ).scalars().all()
    )
    data = {
        "decisions": [
            {
                "id": row.id,
                "action": row.action,
                "reason_code": row.reason_code,
                "evidence_ids": row.evidence_ids,
                "input_state_version": row.input_state_version,
                "planner_source": row.planner_source,
                "model_id": row.model_id,
                "fallback_reason": row.fallback_reason,
                "created_at": row.created_at.isoformat() + "Z",
            }
            for row in rows
        ]
    }
    return envelope(request, data, resource_version=learning_session.version)


@router.post("/sessions/{session_id}/reflection-note")
def save_reflection(
    request: Request,
    db: DbSession,
    student: CurrentStudent,
    session_id: str,
    payload: SaveReflection,
) -> dict:
    def execute(session) -> tuple[dict, int, None]:  # noqa: ANN001
        learning_session = learning_repo.session_owned(session, student.id, session_id)
        if payload.expected_version != learning_session.version:
            from app.domain.errors import VersionConflict

            raise VersionConflict("学习状态已更新，请刷新后继续")
        goal = goals_repo.goal_owned(session, student.id, learning_session.goal_id)
        summary = memory_service.reflection_summary(session, student.id, goal)
        events_repo.record_event(
            session,
            student_id=student.id,
            session_id=learning_session.id,
            type=events_repo.EventType.reflection_saved,
            payload={"text": payload.text, "summary": summary},
            correlation_id=getattr(request.state, "trace_id", None),
        )
        data = {
            "summary": summary,
            "echo": payload.text,
        }
        return data, learning_session.version, None

    return run_idempotent(
        db,
        student_id=student.id,
        request=request,
        payload=payload.model_dump(),
        execute=execute,
    )
