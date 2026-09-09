"""课程内容仓库：概念与题目的查询（评分决策不在此层）。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import QuestionPurpose
from app.infrastructure.models import Concept, Question
from app.infrastructure.repositories.goals import concepts_exist  # re-export 便捷复用

__all__ = ["concepts_exist"]


def concepts_for_course(db: Session, course_id: str) -> list[Concept]:
    return list(
        db.execute(
            select(Concept).where(Concept.course_id == course_id)
        ).scalars().all()
    )


def question_by_id(db: Session, question_id: str) -> Question | None:
    return db.execute(
        select(Question).where(Question.id == question_id)
    ).scalar_one_or_none()


def question_owned(db: Session, question_id: str) -> Question:
    question = question_by_id(db, question_id)
    if question is None:
        from app.domain.errors import ResourceNotFound

        raise ResourceNotFound("题目不存在")
    return question


def screening_candidates_for_concept(
    db: Session, concept_id: str, exclude_question_ids: list[str]
) -> list[Question]:
    """初筛候选：purpose=screening 优先，其次任意未用题，稳定排序。"""
    rows = list(
        db.execute(
            select(Question)
            .where(Question.primary_concept_id == concept_id)
            .order_by(Question.id)
        ).scalars().all()
    )
    excluded = set(exclude_question_ids)
    available = [q for q in rows if q.id not in excluded]
    screening = [q for q in available if q.purpose == QuestionPurpose.screening.value]
    others = [q for q in available if q.purpose != QuestionPurpose.screening.value]
    return screening + others
