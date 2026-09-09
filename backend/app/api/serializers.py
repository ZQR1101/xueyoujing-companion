"""响应 DTO 序列化（§12 数据语义）。"""

from __future__ import annotations

from datetime import datetime, timezone

from app.infrastructure.models import Goal, LearningSession, Student


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).isoformat()


def student_dto(student: Student) -> dict:
    return {
        "id": student.id,
        "display_name": student.display_name,
        "timezone": student.timezone,
        "daily_minutes": student.daily_minutes,
        "created_at": iso(student.created_at),
    }


def goal_dto(goal: Goal) -> dict:
    return {
        "id": goal.id,
        "course_id": goal.course_id,
        "target_concept_ids": goal.target_concept_ids,
        "status": goal.status,
        "version": goal.version,
    }


def session_dto(session: LearningSession) -> dict:
    return {
        "id": session.id,
        "goal_id": session.goal_id,
        "status": session.status,
        "current_task_id": session.current_task_id,
        "version": session.version,
        "updated_at": iso(session.updated_at),
    }


def public_question_dto(question) -> dict:
    """§6/§A15：公开 DTO 显式排除 private_answer / private_hints / numeric_config。"""
    return {
        "id": question.id,
        "course_id": question.course_id,
        "primary_concept_id": question.primary_concept_id,
        "family_id": question.family_id,
        "type": question.type,
        "purpose": question.purpose,
        "prompt": question.prompt,
        "public_options": question.public_options,
        "difficulty": question.difficulty,
        "version": question.version,
    }
