"""计划与任务仓库。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.errors import ResourceNotFound
from app.infrastructure.models import Plan, Task


def plan_owned(db: Session, student_id: str, plan_id: str) -> Plan:
    plan = db.execute(
        select(Plan).where(Plan.id == plan_id, Plan.student_id == student_id)
    ).scalar_one_or_none()
    if plan is None:
        raise ResourceNotFound("计划不存在或不属于当前学生")
    return plan


def latest_plan(db: Session, student_id: str, goal_id: str) -> Plan | None:
    return db.execute(
        select(Plan)
        .where(Plan.student_id == student_id, Plan.goal_id == goal_id)
        .order_by(Plan.version.desc())
    ).scalars().first()


def tasks_for_goal(db: Session, student_id: str, goal_id: str) -> list[Task]:
    return list(
        db.execute(
            select(Task)
            .where(Task.student_id == student_id, Task.goal_id == goal_id)
            .order_by(Task.created_at, Task.id)
        ).scalars().all()
    )


def open_task_for_concept(
    db: Session, student_id: str, goal_id: str, concept_id: str, types: list[str]
) -> Task | None:
    return db.execute(
        select(Task)
        .where(
            Task.student_id == student_id,
            Task.goal_id == goal_id,
            Task.concept_id == concept_id,
            Task.type.in_(types),
            Task.status.in_(["queued", "active"]),
        )
        .order_by(Task.created_at)
    ).scalars().first()


def completed_task_exists(
    db: Session, student_id: str, goal_id: str, concept_id: str, type_: str
) -> bool:
    return (
        db.execute(
            select(Task.id).where(
                Task.student_id == student_id,
                Task.goal_id == goal_id,
                Task.concept_id == concept_id,
                Task.type == type_,
                Task.status == "completed",
            )
        ).scalars().first()
        is not None
    )


def add_task(db: Session, **kwargs) -> Task:
    task = Task(**kwargs)
    db.add(task)
    db.flush()
    return task


def task_owned(db: Session, student_id: str, task_id: str) -> Task:
    task = db.execute(
        select(Task).where(Task.id == task_id, Task.student_id == student_id)
    ).scalar_one_or_none()
    if task is None:
        raise ResourceNotFound("任务不存在或不属于当前学生")
    return task


def set_task_status(db: Session, task: Task, status: str) -> Task:
    task.status = status
    task.version += 1
    db.flush()
    return task


def completed_lesson_exists(db: Session, student_id: str, goal_id: str, concept_id: str) -> bool:
    return completed_task_exists(db, student_id, goal_id, concept_id, "lesson")
