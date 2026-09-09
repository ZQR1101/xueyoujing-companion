"""目标与会话创建服务（§4.1 / §12）。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.domain.enums import EventType, GoalStatus, SessionStatus
from app.domain.errors import IllegalState
from app.infrastructure.models import Goal, LearningSession, Student
from app.infrastructure.repositories import events as events_repo
from app.infrastructure.repositories import goals as goals_repo
from app.infrastructure.repositories import students as students_repo


def create_goal(
    db: Session,
    student: Student,
    *,
    course_id: str,
    target_concept_ids: list[str],
    daily_minutes: int,
    correlation_id: str | None = None,
) -> tuple[Goal, LearningSession]:
    known = goals_repo.concept_ids_for_course(db, course_id)
    if not known:
        raise IllegalState(f"课程 {course_id} 不存在或尚未导入知识点")
    targets = target_concept_ids or known
    unknown = set(targets) - set(known)
    if unknown:
        raise IllegalState(f"未知知识点：{sorted(unknown)}")
    if len(set(targets)) != len(targets):
        raise IllegalState("target_concept_ids 存在重复项")

    students_repo.update_daily_minutes(db, student, daily_minutes)
    goal = Goal(
        student_id=student.id,
        course_id=course_id,
        target_concept_ids=targets,
        status=GoalStatus.active.value,
    )
    db.add(goal)
    db.flush()
    session = LearningSession(
        student_id=student.id,
        goal_id=goal.id,
        status=SessionStatus.ready.value,
    )
    db.add(session)
    db.flush()
    events_repo.record_event(
        db,
        student_id=student.id,
        session_id=session.id,
        type=EventType.goal_created,
        payload={
            "goal_id": goal.id,
            "course_id": course_id,
            "target_concept_ids": targets,
            "daily_minutes": daily_minutes,
        },
        correlation_id=correlation_id,
    )
    return goal, session
