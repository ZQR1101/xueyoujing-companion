"""目标与会话仓库：一律按 student_id 过滤（A11 隔离）。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.errors import ResourceNotFound
from app.infrastructure.models import Concept, Goal, LearningSession


def goal_owned(db: Session, student_id: str, goal_id: str) -> Goal:
    goal = db.execute(
        select(Goal).where(Goal.id == goal_id, Goal.student_id == student_id)
    ).scalar_one_or_none()
    if goal is None:
        raise ResourceNotFound("目标不存在或不属于当前学生")
    return goal


def session_owned(db: Session, student_id: str, session_id: str) -> LearningSession:
    session = db.execute(
        select(LearningSession).where(
            LearningSession.id == session_id,
            LearningSession.student_id == student_id,
        )
    ).scalar_one_or_none()
    if session is None:
        raise ResourceNotFound("学习会话不存在或不属于当前学生")
    return session


def concept_ids_for_course(db: Session, course_id: str) -> list[str]:
    rows = db.execute(
        select(Concept.id).where(Concept.course_id == course_id)
    ).scalars().all()
    return sorted(rows)


def concepts_exist(db: Session, course_id: str, concept_ids: list[str]) -> bool:
    if not concept_ids:
        return True
    rows = db.execute(
        select(Concept.id).where(
            Concept.course_id == course_id, Concept.id.in_(concept_ids)
        )
    ).scalars().all()
    return set(rows) == set(concept_ids)


def bump_version(entity: Goal | LearningSession) -> int:
    entity.version += 1
    return entity.version
