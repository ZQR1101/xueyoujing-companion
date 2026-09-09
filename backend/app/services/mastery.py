"""掌握度更新管线（§7）：证据有效性判定 + 投影重建 + 快照 + 事件。

规则（§7.1）：
- 有效证据 = 已核验题、该练习首答、无提示、未看解析；错误同样有效；
- 每个学生每个 family_id 至多一份有效证据（另有部分唯一索引兜底）；
- 投影一律整体重算，不做反向减分补丁（§7.3）。
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.domain.enums import EventType, MasteryStatus
from app.domain.mastery import (
    FORMULA_VERSION,
    EvidenceSlice,
    MasteryProjection,
    project,
    projection_dto,
)
from app.infrastructure.config import get_settings
from app.infrastructure.models import Attempt, Evidence, MasterySnapshot, Question
from app.infrastructure.repositories import events as events_repo
from app.infrastructure.repositories import learning as learning_repo
from app.services import memory as memory_service

NOT_FIRST_ATTEMPT_REASON = "not_first_attempt"
HINT_USED_REASON = "hint_used"
SOLUTION_SEEN_REASON = "solution_seen"
FAMILY_DUPLICATE_REASON = "family_already_counted"


def _exclusion_reason(
    db: Session,
    *,
    student_id: str,
    question: Question,
    attempt: Attempt,
    exercise,
    prior_attempts: int,
) -> str | None:
    # 顺序按对演示/辅导的信息量：看解析最明确，其次非首答，再次带提示
    if exercise.solution_seen:
        return SOLUTION_SEEN_REASON
    if prior_attempts > 0:
        return NOT_FIRST_ATTEMPT_REASON
    if attempt.hint_level_at_submission > 0:
        return HINT_USED_REASON
    if learning_repo.eligible_evidence_exists(db, student_id, question.family_id):
        return FAMILY_DUPLICATE_REASON
    return None


def apply_attempt_evidence(
    db: Session,
    *,
    student_id: str,
    exercise,
    question: Question,
    attempt: Attempt,
    prior_attempts: int,
    correlation_id: str | None,
) -> tuple[Evidence, MasteryProjection, MasteryProjection]:
    """为一次作答写证据行；若有效则重建掌握投影。

    返回 (evidence, before, after)：after 在证据无效时等于 before。
    """
    exercise_id = exercise.id
    before_slices = learning_repo.evidence_slices_for_concept(
        db, student_id, question.primary_concept_id
    )
    before = project(before_slices)

    graded_event = events_repo.record_event(
        db,
        student_id=student_id,
        type=EventType.answer_graded,
        payload={
            "attempt_id": attempt.id,
            "exercise_id": exercise_id,
            "question_id": question.id,
            "grade": attempt.grade,
        },
        correlation_id=correlation_id,
    )

    exclusion_reason = _exclusion_reason(
        db,
        student_id=student_id,
        question=question,
        attempt=attempt,
        exercise=exercise,
        prior_attempts=prior_attempts,
    )
    eligible = exclusion_reason is None

    evidence = Evidence(
        student_id=student_id,
        concept_id=question.primary_concept_id,
        attempt_id=attempt.id,
        family_id=question.family_id,
        score=1 if attempt.grade == "correct" else 0,
        eligible=eligible,
        exclusion_reason=exclusion_reason,
        event_id=graded_event.id,
    )
    db.add(evidence)
    db.flush()

    after = before
    if eligible:
        after = project(before_slices + [EvidenceSlice(evidence.id, evidence.score)])
        review_due = None
        if after.status is MasteryStatus.mastered:
            interval = get_settings().review_interval_days
            review_due = attempt.created_at + timedelta(days=interval)
        learning_repo.save_mastery_state(
            db,
            student_id=student_id,
            concept_id=question.primary_concept_id,
            estimate=after.estimate,
            evidence_count=after.evidence_count,
            evidence_strength=after.evidence_strength,
            status=after.status.value,
            recent_evidence_ids=after.recent_evidence_ids,
            review_due_at=review_due,
        )
        mastery_event = events_repo.record_event(
            db,
            student_id=student_id,
            type=EventType.mastery_updated,
            payload={
                "concept_id": question.primary_concept_id,
                "formula_version": FORMULA_VERSION,
                "evidence_id": evidence.id,
                "before": projection_dto(before),
                "after": projection_dto(after),
            },
            correlation_id=correlation_id,
        )
        memory_service.record_mastery_fact(
            db,
            student_id=student_id,
            concept_id=question.primary_concept_id,
            event_id=mastery_event.id,
            estimate=after.estimate,
            evidence_count=after.evidence_count,
            status=after.status.value,
        )

    db.add(
        MasterySnapshot(
            student_id=student_id,
            concept_id=question.primary_concept_id,
            evidence_id=evidence.id,
            attempt_id=attempt.id,
            formula_version=FORMULA_VERSION,
            before=projection_dto(before),
            after=projection_dto(after),
        )
    )
    db.flush()
    return evidence, before, after
