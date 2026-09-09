"""路径规划器 v1（规则，§9.2/§9.3）。

职责边界（§5）：规则负责知识点 ID、依赖、预算与证据有效性；
LLM 只能在合法范围内选择行动（T07 coordinator），不得绕过先修条件。

排序（§9.2 的确定性实现，同一层内稳定）：
  1. 复习到期（mastered 且 review_due_at 已过）优先；
  2. 合法节点（全部前置已 mastered）中未评估者进入补测；
  3. 其余合法未掌握节点按 estimate 升序 → 重复错误数降序 → concept_id；
  4. 前置未掌握的节点锁定，不产生任务（预览可见）；
  5. 已 mastered 且未到期的排最后，不产生任务。

版本（§9.3 / A07）：仅当有序概念序列真正变化才升 Plan.version；
任务物化遵循 daily_minutes 预算（A06），已完成任务保持不变。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.domain.enums import EventType, MasteryStatus, SessionStatus, TaskStatus, TaskType
from app.infrastructure.curriculum import get_course_data
from app.infrastructure.models import Goal, LearningSession, Plan, Student
from app.infrastructure.repositories import events as events_repo
from app.infrastructure.repositories import learning as learning_repo
from app.infrastructure.repositories import plans as plans_repo

POLICY_VERSION = "v1-rules"
TASK_MINUTES = 5


@dataclass(frozen=True)
class NodeState:
    concept_id: str
    title: str
    status: str  # review_due / unassessed / developing / needs_support / mastered / locked
    reason: str
    review_due_at: str | None
    eligible: bool


def _to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).isoformat()


def distinct_error_exercises(db: Session, student_id: str, concept_id: str) -> int:
    """同类错误统计（§9.3）：不同题的错答计数，同题多次重试算一题。"""
    rows = db.execute(
        text(
            """
            SELECT COUNT(DISTINCT e.id)
            FROM attempts a
            JOIN exercises e ON e.id = a.exercise_id
            JOIN questions q ON q.id = e.question_id
            WHERE a.student_id = :sid AND q.primary_concept_id = :cid AND a.grade = 'incorrect'
            """
        ),
        {"sid": student_id, "cid": concept_id},
    ).scalar()
    return int(rows or 0)


def _classify(
    db: Session,
    student: Student,
    goal: Goal,
) -> tuple[list[str], dict[str, NodeState], list[str]]:
    course = get_course_data()
    targets = [c for c in course.topo_order if c in set(goal.target_concept_ids)]
    states = learning_repo.mastery_states_for_concepts(db, student.id, targets)
    now = datetime.utcnow()

    mastered_ids = {
        cid
        for cid in targets
        if states.get(cid) is not None and states[cid].status == MasteryStatus.mastered.value
    }

    def eligible(cid: str) -> bool:
        return all(pre in mastered_ids for pre in course.prerequisites.get(cid, []))

    nodes: dict[str, NodeState] = {}
    working: list[str] = []
    locked: list[str] = []

    review_due, unassessed, weak = [], [], []
    mastered_rest: list[str] = []

    for cid in targets:
        state = states.get(cid)
        title = course.concept(cid)["title"] if course.concept(cid) else cid
        missing_pre = [p for p in course.prerequisites.get(cid, []) if p not in mastered_ids]
        if missing_pre:
            nodes[cid] = NodeState(
                cid, title, "locked",
                "前置未掌握：" + "、".join(missing_pre),
                None, False,
            )
            locked.append(cid)
            continue
        if state is None or state.evidence_count == 0:
            nodes[cid] = NodeState(cid, title, "unassessed", "尚未评估，进入诊断补测", None, True)
            unassessed.append(cid)
            continue
        due = state.review_due_at is not None and state.review_due_at <= now
        if state.status == MasteryStatus.mastered.value:
            if due:
                nodes[cid] = NodeState(
                    cid, title, "review_due", "复习到期，安排复测", _to_iso(state.review_due_at), True
                )
                review_due.append(cid)
            else:
                nodes[cid] = NodeState(cid, title, "mastered", "已掌握", _to_iso(state.review_due_at), True)
                mastered_rest.append(cid)
            continue
        if state.status == MasteryStatus.needs_support.value:
            reason = "证据不足（needs_support）"
            status = "needs_support"
        else:
            reason = "掌握发展中"
            status = "developing"
        errors = distinct_error_exercises(db, student.id, cid)
        if errors >= 2:
            reason += f"；{errors} 道不同题出现错误"
        nodes[cid] = NodeState(cid, title, status, reason, _to_iso(state.review_due_at), True)
        weak.append(cid)

    weak.sort(key=lambda c: (
        states[c].estimate if states[c].estimate is not None else 1.0,
        -distinct_error_exercises(db, student.id, c),
        c,
    ))
    working = review_due + unassessed + weak + mastered_rest
    return working, nodes, locked


def _materialize_tasks(
    db: Session,
    *,
    student: Student,
    goal: Goal,
    ordered: list[str],
    nodes: dict[str, NodeState],
    plan_version: int,
) -> list[Task]:
    """按预算物化任务：已完成任务保持不变，同概念已有排队任务则复用；
    概念已掌握/锁定后遗留的排队任务取消（§9.3「其余待办可调整」）。"""
    budget = student.daily_minutes
    created: list[Task] = []

    existing = [
        t for t in plans_repo.tasks_for_goal(db, student.id, goal.id)
        if t.status in (TaskStatus.queued.value, TaskStatus.active.value)
    ]
    for t in existing:
        node = nodes.get(t.concept_id)
        if t.status == TaskStatus.queued.value and (
            node is None or not node.eligible or node.status == "mastered"
        ):
            t.status = TaskStatus.cancelled.value
            t.version += 1
    db.flush()
    existing = [t for t in existing if t.status == TaskStatus.active.value]
    used = sum(t.estimated_minutes for t in existing)
    covered = {t.concept_id for t in existing}

    def budget_left() -> int:
        return budget - used - sum(t.estimated_minutes for t in created)

    for cid in ordered:
        node = nodes.get(cid)
        if node is None or not node.eligible or node.status == "mastered":
            continue
        if cid in covered:
            continue

        if node.status == "review_due":
            if budget_left() < TASK_MINUTES:
                continue
            created.append(
                plans_repo.add_task(
                    db,
                    student_id=student.id,
                    goal_id=goal.id,
                    plan_version=plan_version,
                    concept_id=cid,
                    type=TaskType.review.value,
                    status=TaskStatus.queued.value,
                    estimated_minutes=TASK_MINUTES,
                )
            )
            continue

        if not plans_repo.completed_lesson_exists(db, student.id, goal.id, cid):
            if budget_left() < TASK_MINUTES:
                continue
            created.append(
                plans_repo.add_task(
                    db,
                    student_id=student.id,
                    goal_id=goal.id,
                    plan_version=plan_version,
                    concept_id=cid,
                    type=TaskType.lesson.value,
                    status=TaskStatus.queued.value,
                    estimated_minutes=TASK_MINUTES,
                )
            )
        if budget_left() < TASK_MINUTES:
            continue
        created.append(
            plans_repo.add_task(
                db,
                student_id=student.id,
                goal_id=goal.id,
                plan_version=plan_version,
                concept_id=cid,
                type=TaskType.practice.value,
                status=TaskStatus.queued.value,
                estimated_minutes=TASK_MINUTES,
            )
        )
    return created


def generate_plan(
    db: Session,
    *,
    student: Student,
    goal: Goal,
    reason_code: str,
    evidence_ids: list[str] | None = None,
    correlation_id: str | None = None,
) -> tuple[Plan, bool]:
    """生成/更新计划。返回 (plan, changed)。

    §9.3：路径顺序、任务集合或节点状态真正变化才升版（A07）。
    节点状态快照存入 Plan.node_status_snapshot 供比对。
    """
    working, nodes, locked = _classify(db, student, goal)
    ordered = working + locked
    signature = {cid: nodes[cid].status for cid in ordered}
    previous = plans_repo.latest_plan(db, student.id, goal.id)

    if (
        previous is not None
        and previous.ordered_concept_ids == ordered
        and (previous.node_status_snapshot or {}) == signature
    ):
        # 计划无变化不升版（A07），但已消耗的任务仍需幂等补种，
        # 否则诊断/复习完成后任务清单会永久为空。
        created = _materialize_tasks(
            db, student=student, goal=goal, ordered=ordered, nodes=nodes, plan_version=previous.version
        )
        if created:
            previous.active_task_ids = [
                t.id
                for t in plans_repo.tasks_for_goal(db, student.id, goal.id)
                if t.status in (TaskStatus.queued.value, TaskStatus.active.value)
            ]
            db.flush()
        return previous, False

    plan = Plan(
        student_id=student.id,
        goal_id=goal.id,
        version=(previous.version + 1) if previous else 1,
        ordered_concept_ids=ordered,
        node_status_snapshot=signature,
        active_task_ids=[],
        reason_code=reason_code,
        evidence_ids=list(evidence_ids or []),
        policy_version=POLICY_VERSION,
    )
    db.add(plan)
    db.flush()

    created = _materialize_tasks(
        db, student=student, goal=goal, ordered=ordered, nodes=nodes, plan_version=plan.version
    )
    plan.active_task_ids = [
        t.id
        for t in plans_repo.tasks_for_goal(db, student.id, goal.id)
        if t.status in (TaskStatus.queued.value, TaskStatus.active.value)
    ]
    db.flush()

    events_repo.record_event(
        db,
        student_id=student.id,
        type=EventType.plan_changed,
        payload={
            "plan_id": plan.id,
            "version": plan.version,
            "reason_code": reason_code,
            "previous_version": previous.version if previous else None,
            "ordered_concept_ids": ordered,
            "created_task_ids": [t.id for t in created],
            "policy_version": POLICY_VERSION,
        },
        correlation_id=correlation_id,
    )
    return plan, True


def ordered_tasks(db: Session, student_id: str, goal_id: str, plan: Plan) -> list:
    """按计划的概念顺序输出任务（复习→补测→弱项→锁定无任务）。"""
    tasks = [
        t for t in plans_repo.tasks_for_goal(db, student.id, goal_id)
        if t.status in (TaskStatus.queued.value, TaskStatus.active.value, TaskStatus.completed.value)
    ]
    order_index = {cid: i for i, cid in enumerate(plan.ordered_concept_ids)}
    return sorted(tasks, key=lambda t: order_index.get(t.concept_id, 999))


def next_startable_task(db: Session, student_id: str, goal_id: str, plan: Plan):
    """下一个可开始任务：优先恢复 active，其次按计划顺序取 queued。"""
    tasks = [
        t for t in plans_repo.tasks_for_goal(db, student_id, goal_id)
        if t.status in (TaskStatus.queued.value, TaskStatus.active.value)
    ]
    if not tasks:
        return None
    order_index = {cid: i for i, cid in enumerate(plan.ordered_concept_ids)}
    tasks.sort(key=lambda t: (
        0 if t.status == TaskStatus.active.value else 1,
        order_index.get(t.concept_id, 999),
        0 if t.type == TaskType.lesson.value else 1,
        t.created_at,
    ))
    return tasks[0]


def ensure_session_learning(db: Session, session: LearningSession, expected_version: int) -> None:
    learning_repo.bump_learning_session_version(db, session.id, expected_version)
    db.refresh(session)
    session.status = SessionStatus.learning.value


def path_view(db: Session, *, student: Student, goal: Goal) -> dict:
    """只读路径视图：当前计划 + 节点状态与依据 + 前后版本（读接口零写入）。"""
    working, nodes, locked = _classify(db, student, goal)
    latest = plans_repo.latest_plan(db, student.id, goal.id)
    ordered = working + locked
    previous = None
    if latest is not None and latest.version > 1:
        prev_row = db.execute(
            select(Plan)
            .where(
                Plan.student_id == student.id,
                Plan.goal_id == goal.id,
                Plan.version == latest.version - 1,
            )
        ).scalar_one_or_none()
        previous = (
            {"id": prev_row.id, "version": prev_row.version,
             "ordered_concept_ids": prev_row.ordered_concept_ids,
             "reason_code": prev_row.reason_code}
            if prev_row
            else None
        )

    stale = (
        latest is None
        or latest.ordered_concept_ids != ordered
        or (latest.node_status_snapshot or {}) != {cid: nodes[cid].status for cid in ordered}
    )

    tasks = plans_repo.tasks_for_goal(db, student.id, goal.id)
    tasks_by_concept: dict[str, list] = {}
    for t in tasks:
        if t.status in (TaskStatus.queued.value, TaskStatus.active.value, TaskStatus.completed.value):
            tasks_by_concept.setdefault(t.concept_id, []).append(
                {"id": t.id, "type": t.type, "status": t.status, "estimated_minutes": t.estimated_minutes}
            )

    node_list = []
    for cid in ordered:
        node = nodes[cid]
        node_list.append(
            {
                "concept_id": node.concept_id,
                "title": node.title,
                "status": node.status,
                "reason": node.reason,
                "eligible": node.eligible,
                "review_due_at": node.review_due_at,
                "tasks": tasks_by_concept.get(cid, []),
            }
        )

    return {
        "plan": {
            "id": latest.id,
            "version": latest.version,
            "ordered_concept_ids": latest.ordered_concept_ids,
            "reason_code": latest.reason_code,
            "policy_version": latest.policy_version,
            "active_task_ids": latest.active_task_ids,
        }
        if latest is not None
        else None,
        "nodes": node_list,
        "previous_plan": previous,
        "stale": stale,
        "stale_note": "学习状态已变化，重算后的顺序与当前计划不同；调用 replan 可更新计划。" if stale else None,
    }
