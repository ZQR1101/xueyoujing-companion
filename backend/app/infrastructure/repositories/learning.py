"""学习域仓库：会话/评估/练习/作答/证据/掌握状态的查询与标量写。

只做数据访问与归属过滤（A11），不做教学决策、不开事务。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.domain.errors import ResourceNotFound, VersionConflict
from app.domain.mastery import EvidenceSlice
from app.infrastructure.models import (
    Assessment,
    Attempt,
    Evidence,
    Exercise,
    LearningSession,
    MasteryState,
    Plan,
)

# ---- 归属读取 ----


def session_owned(db: Session, student_id: str, session_id: str) -> LearningSession:
    session_row = db.execute(
        select(LearningSession).where(
            LearningSession.id == session_id,
            LearningSession.student_id == student_id,
        )
    ).scalar_one_or_none()
    if session_row is None:
        raise ResourceNotFound("学习会话不存在或不属于当前学生")
    return session_row


def session_for_goal(db: Session, student_id: str, goal_id: str) -> LearningSession | None:
    return db.execute(
        select(LearningSession)
        .where(LearningSession.student_id == student_id, LearningSession.goal_id == goal_id)
        .order_by(LearningSession.created_at)
    ).scalars().first()


def assessment_owned(db: Session, student_id: str, assessment_id: str) -> Assessment:
    assessment = db.execute(
        select(Assessment).where(
            Assessment.id == assessment_id,
            Assessment.student_id == student_id,
        )
    ).scalar_one_or_none()
    if assessment is None:
        raise ResourceNotFound("诊断不存在或不属于当前学生")
    return assessment


def exercise_owned(db: Session, student_id: str, exercise_id: str) -> Exercise:
    exercise = db.execute(
        select(Exercise).where(
            Exercise.id == exercise_id,
            Exercise.student_id == student_id,
        )
    ).scalar_one_or_none()
    if exercise is None:
        raise ResourceNotFound("练习不存在或不属于当前学生")
    return exercise


def exercises_for_assessment(db: Session, assessment: Assessment) -> list[Exercise]:
    """按 assessment.question_ids 的顺序返回（题目呈现顺序即合同顺序）。"""
    rows = list(
        db.execute(
            select(Exercise).where(Exercise.assessment_id == assessment.id)
        ).scalars().all()
    )
    order_index = {qid: i for i, qid in enumerate(assessment.question_ids)}
    return sorted(rows, key=lambda e: order_index.get(e.question_id, len(order_index)))


def attempts_for_exercise(db: Session, exercise_id: str) -> list[Attempt]:
    return list(
        db.execute(
            select(Attempt)
            .where(Attempt.exercise_id == exercise_id)
            .order_by(Attempt.created_at, Attempt.id)
        ).scalars().all()
    )


def in_progress_assessment_for_goal(
    db: Session, student_id: str, goal_id: str
) -> Assessment | None:
    return db.execute(
        select(Assessment).where(
            Assessment.student_id == student_id,
            Assessment.goal_id == goal_id,
            Assessment.status == "in_progress",
        )
    ).scalar_one_or_none()


def student_attempted_question_ids(db: Session, student_id: str) -> list[str]:
    rows = db.execute(
        select(Exercise.question_id)
        .where(Exercise.student_id == student_id)
        .distinct()
    ).scalars().all()
    return list(rows)


# ---- 乐观版本（A09）----


def close_exercise_guarded(
    db: Session, exercise_id: str, expected_version: int
) -> None:
    result = db.execute(
        update(Exercise)
        .where(Exercise.id == exercise_id, Exercise.version == expected_version)
        .values(status="closed", version=expected_version + 1)
    )
    if result.rowcount == 0:
        raise VersionConflict("练习状态已更新，请刷新后继续")


def patch_exercise_guarded(
    db: Session, exercise_id: str, expected_version: int, **values
) -> None:
    """带版本守卫的字段更新（练习保持 open，如提示等级/解析标记）。"""
    result = db.execute(
        update(Exercise)
        .where(Exercise.id == exercise_id, Exercise.version == expected_version)
        .values(**values, version=expected_version + 1)
    )
    if result.rowcount == 0:
        raise VersionConflict("练习状态已更新，请刷新后继续")


def bump_assessment_version(db: Session, assessment_id: str, expected_version: int) -> int:
    result = db.execute(
        update(Assessment)
        .where(Assessment.id == assessment_id, Assessment.version == expected_version)
        .values(version=expected_version + 1)
    )
    if result.rowcount == 0:
        raise VersionConflict("评估状态已更新，请刷新后继续")
    return expected_version + 1


def bump_learning_session_version(
    db: Session, session_id: str, expected_version: int
) -> int:
    result = db.execute(
        update(LearningSession)
        .where(
            LearningSession.id == session_id,
            LearningSession.version == expected_version,
        )
        .values(version=expected_version + 1)
    )
    if result.rowcount == 0:
        raise VersionConflict("学习状态已更新，请刷新后继续")
    return expected_version + 1


# ---- 证据与掌握 ----


def eligible_evidence_exists(db: Session, student_id: str, family_id: str) -> bool:
    return (
        db.execute(
            select(Evidence.id).where(
                Evidence.student_id == student_id,
                Evidence.family_id == family_id,
                Evidence.eligible == True,  # noqa: E712
            )
        ).scalar_one_or_none()
        is not None
    )


def evidence_slices_for_concept(
    db: Session, student_id: str, concept_id: str
) -> list[EvidenceSlice]:
    rows = db.execute(
        select(Evidence.id, Evidence.score)
        .where(
            Evidence.student_id == student_id,
            Evidence.concept_id == concept_id,
            Evidence.eligible == True,  # noqa: E712
        )
        .order_by(Evidence.created_at, Evidence.id)
    ).all()
    return [EvidenceSlice(evidence_id=eid, score=score) for eid, score in rows]


def mastery_state(db: Session, student_id: str, concept_id: str) -> MasteryState | None:
    return db.execute(
        select(MasteryState).where(
            MasteryState.student_id == student_id,
            MasteryState.concept_id == concept_id,
        )
    ).scalar_one_or_none()


def save_mastery_state(
    db: Session,
    *,
    student_id: str,
    concept_id: str,
    estimate: float | None,
    evidence_count: int,
    evidence_strength: float,
    status: str,
    recent_evidence_ids: list[str],
    review_due_at: datetime | None,
) -> MasteryState:
    state = mastery_state(db, student_id, concept_id)
    if state is None:
        state = MasteryState(
            student_id=student_id,
            concept_id=concept_id,
            estimate=estimate,
            evidence_count=evidence_count,
            evidence_strength=evidence_strength,
            status=status,
            recent_evidence_ids=recent_evidence_ids,
            review_due_at=review_due_at,
            version=1,
        )
        db.add(state)
    else:
        state.estimate = estimate
        state.evidence_count = evidence_count
        state.evidence_strength = evidence_strength
        state.status = status
        state.recent_evidence_ids = list(recent_evidence_ids)
        state.review_due_at = review_due_at
        state.version += 1
    db.flush()
    return state


def mastery_states_for_concepts(
    db: Session, student_id: str, concept_ids: list[str]
) -> dict[str, MasteryState]:
    if not concept_ids:
        return {}
    rows = db.execute(
        select(MasteryState).where(
            MasteryState.student_id == student_id,
            MasteryState.concept_id.in_(concept_ids),
        )
    ).scalars().all()
    return {row.concept_id: row for row in rows}


def latest_evidences(db: Session, student_id: str, limit: int = 8) -> list[Evidence]:
    return list(
        db.execute(
            select(Evidence)
            .where(Evidence.student_id == student_id)
            .order_by(Evidence.created_at.desc(), Evidence.id.desc())
            .limit(limit)
        ).scalars().all()
    )


def latest_plan(db: Session, student_id: str, goal_id: str) -> Plan | None:
    return db.execute(
        select(Plan)
        .where(Plan.student_id == student_id, Plan.goal_id == goal_id)
        .order_by(Plan.version.desc())
    ).scalars().first()
