"""只读查询服务（§12：读接口不得触发规划或写状态）。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.curriculum import get_course_data
from app.infrastructure.models import (
    Evidence,
    Goal,
    LearningSession,
    MasterySnapshot,
    Student,
)
from app.infrastructure.repositories import learning as learning_repo


def _mastery_entry(db: Session, student_id: str, concept_id: str) -> dict:
    state = learning_repo.mastery_state(db, student_id, concept_id)
    course = get_course_data()
    concept = course.concept(concept_id)
    if state is None:
        return {
            "concept_id": concept_id,
            "title": concept["title"] if concept else concept_id,
            "estimate": None,
            "evidence_count": 0,
            "evidence_strength": 0.0,
            "status": "unassessed",
            "review_due_at": None,
        }
    return {
        "concept_id": concept_id,
        "title": concept["title"] if concept else concept_id,
        "estimate": state.estimate,
        "evidence_count": state.evidence_count,
        "evidence_strength": state.evidence_strength,
        "status": state.status,
        "review_due_at": state.review_due_at.isoformat() + "Z" if state.review_due_at else None,
    }


def evidence_dto(evidence: Evidence) -> dict:
    return {
        "id": evidence.id,
        "concept_id": evidence.concept_id,
        "attempt_id": evidence.attempt_id,
        "family_id": evidence.family_id,
        "score": evidence.score,
        "eligible": evidence.eligible,
        "exclusion_reason": evidence.exclusion_reason,
        "created_at": evidence.created_at.isoformat() + "Z",
    }


def build_overview(db: Session, student: Student) -> dict:
    goals = list(
        db.execute(
            select(Goal)
            .where(Goal.student_id == student.id, Goal.status == "active")
            .order_by(Goal.created_at)
        ).scalars().all()
    )
    recent = learning_repo.latest_evidences(db, student.id, limit=8)

    goal_entries = []
    for goal in goals:
        targets = list(goal.target_concept_ids)
        mastery = [_mastery_entry(db, student.id, cid) for cid in targets]
        assessed = sum(1 for m in mastery if m["status"] != "unassessed")
        sessions = list(
            db.execute(
                select(LearningSession)
                .where(
                    LearningSession.student_id == student.id,
                    LearningSession.goal_id == goal.id,
                )
                .order_by(LearningSession.created_at.desc())
            ).scalars().all()
        )
        goal_entries.append(
            {
                "goal": {
                    "id": goal.id,
                    "course_id": goal.course_id,
                    "target_concept_ids": targets,
                    "status": goal.status,
                    "version": goal.version,
                },
                "coverage": {
                    "assessed_count": assessed,
                    "total_count": len(targets),
                    "ratio": round(assessed / len(targets), 4) if targets else 0.0,
                },
                "mastery": mastery,
                "latest_session": {
                    "id": sessions[0].id,
                    "status": sessions[0].status,
                    "version": sessions[0].version,
                }
                if sessions
                else None,
            }
        )

    return {
        "student": {
            "id": student.id,
            "display_name": student.display_name,
            "daily_minutes": student.daily_minutes,
            "timezone": student.timezone,
        },
        "goals": goal_entries,
        "recent_evidence": [evidence_dto(e) for e in reversed(recent)],
        "today_tasks": [],
    }


def mastery_history(db: Session, student: Student, concept_id: str) -> dict:
    rows = list(
        db.execute(
            select(MasterySnapshot)
            .where(
                MasterySnapshot.student_id == student.id,
                MasterySnapshot.concept_id == concept_id,
            )
            .order_by(MasterySnapshot.created_at, MasterySnapshot.id)
        ).scalars().all()
    )
    course = get_course_data()
    concept = course.concept(concept_id)
    return {
        "concept_id": concept_id,
        "title": concept["title"] if concept else concept_id,
        "formula_version": rows[0].formula_version if rows else None,
        "points": [
            {
                "attempt_id": row.attempt_id,
                "evidence_id": row.evidence_id,
                "before": row.before,
                "after": row.after,
                "created_at": row.created_at.isoformat() + "Z",
            }
            for row in rows
        ],
    }
