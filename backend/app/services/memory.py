"""记忆服务（§11）：L1=事件（events 表），L2=有引用的事实（memory_facts），
L3=可重建的上下文投影（build_context，只读计算）。

- SQLite 是唯一事实源，不另设 JSONL 存储。
- 记忆输入限流：当前目标、当前任务、近期最多 8 份相关证据、相关错误、
  学生明确表达的偏好（偏好暂无写入端点，字段留待 T08/T09）。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import MasteryStatus
from app.infrastructure.curriculum import get_course_data
from app.infrastructure.models import Event, Evidence, Goal, LearningSession, MemoryFact, Task
from app.infrastructure.repositories import learning as learning_repo


def record_mastery_fact(
    db: Session,
    *,
    student_id: str,
    concept_id: str,
    event_id: str,
    estimate: float | None,
    evidence_count: int,
    status: str,
) -> MemoryFact:
    """掌握投影变化 → L2 事实（旧同概念事实标记 superseded，保留证据引用链）。"""
    course = get_course_data()
    concept = course.concept(concept_id)
    title = concept["title"] if concept else concept_id

    previous = db.execute(
        select(MemoryFact)
        .where(
            MemoryFact.student_id == student_id,
            MemoryFact.course_id == course.course_id,
            MemoryFact.concept_id == concept_id,
            MemoryFact.type == "mastery_summary",
            MemoryFact.status == "active",
        )
        .order_by(MemoryFact.created_at.desc())
    ).scalars().first()
    if previous is not None:
        previous.status = "superseded"

    fact = MemoryFact(
        student_id=student_id,
        course_id=course.course_id,
        concept_id=concept_id,
        type="mastery_summary",
        content=(
            f"[{concept_id}] {title}：掌握状态 {status}，"
            f"estimate={estimate if estimate is not None else 'null'}，"
            f"有效证据 {evidence_count} 份"
        ),
        evidence_event_ids=[event_id],
        status="active",
        version=(previous.version + 1 if previous else 1),
        supersedes_id=previous.id if previous else None,
    )
    db.add(fact)
    db.flush()
    return fact


def build_context(
    db: Session,
    *,
    student_id: str,
    session: LearningSession,
    goal: Goal | None,
    task: Task | None,
) -> dict:
    """L3 投影：给 coordinator/LLM 的受限上下文（不做全量聊天拼装）。"""
    course = get_course_data()
    evidences = learning_repo.latest_evidences(db, student_id, limit=8)

    current_task = None
    if task is not None:
        concept = course.concept(task.concept_id)
        current_task = {
            "task_id": task.id,
            "concept_id": task.concept_id,
            "concept_title": concept["title"] if concept else task.concept_id,
            "type": task.type,
            "status": task.status,
        }

    repeated_errors = []
    for evidence in evidences:
        if evidence.score == 0 and evidence.eligible:
            concept = course.concept(evidence.concept_id)
            repeated_errors.append(
                {
                    "concept_id": evidence.concept_id,
                    "concept_title": concept["title"] if concept else evidence.concept_id,
                    "evidence_id": evidence.id,
                }
            )

    fact_query = (
        select(MemoryFact)
        .where(
            MemoryFact.student_id == student_id,
            MemoryFact.status == "active",
            MemoryFact.type.in_(["mastery_summary", "reflection_fact"]),
        )
        .order_by(MemoryFact.created_at.desc())
        .limit(16)
    )
    if goal is not None:
        fact_query = fact_query.where(MemoryFact.course_id == goal.course_id)
    facts = [fact for fact in db.execute(fact_query).scalars().all() if fact.evidence_event_ids][:8]

    return {
        "goal": {
            "goal_id": goal.id,
            "course_id": goal.course_id,
            "target_concept_ids": goal.target_concept_ids,
        }
        if goal
        else None,
        "session_status": session.status,
        "current_task": current_task,
        "recent_evidence": [
            {
                "evidence_id": e.id,
                "concept_id": e.concept_id,
                "score": e.score,
                "eligible": e.eligible,
                "exclusion_reason": e.exclusion_reason,
            }
            for e in reversed(evidences)
        ],
        "repeated_errors": repeated_errors,
        # T14-B: Planner/Coordinator consume only active, evidence-backed facts.
        "memory_facts": [{"id": f.id, "concept_id": f.concept_id, "content": f.content,
                          "evidence_event_ids": f.evidence_event_ids} for f in facts],
        "preferences": [],
    }


def reflection_summary(db: Session, student_id: str, goal: Goal) -> dict:
    """规则小结：不依赖 LLM，确定性生成。"""
    states = learning_repo.mastery_states_for_concepts(
        db, student_id, list(goal.target_concept_ids)
    )
    mastered = [
        cid for cid, s in states.items() if s.status == MasteryStatus.mastered.value
    ]
    evidences = learning_repo.latest_evidences(db, student_id, limit=8)
    return {
        "mastered_concept_ids": sorted(mastered),
        "total_target": len(goal.target_concept_ids),
        "evidence_count_total": sum(s.evidence_count for s in states.values()),
        "recent_evidence_ids": [e.id for e in reversed(evidences)],
        "note": "小结由确定性状态生成；自然语言总结可在在线模式下重试生成。",
    }
