"""T11-B LLM 路径决策（在规则 Planner 的合法候选之上做选择与解释）。

流程（规划书 T11-B，固定顺序）：
  读取学习状态 → 规则生成候选行动 → 调用 LLM → Schema 校验
  → 校验 action/target/evidence 归属 → 执行合法行动 → 写入决策轨迹
  → 必要时生成新 Plan.version（仅任务集合真实变化时）。

约束：
- candidate_actions 由规则层生成，LLM 不得追加行动；
- target_id / evidence_id 必须存在且属于当前学生与课程；
- LLM 不得直接写掌握度、解锁节点或删除任务——执行器是规则代码；
- 路径无实际变化不升 Plan.version；候选为空返回 no_legal_action，不伪造任务；
- 相同输入/规则版本/候选集合可重放（input_state_hash 快照）；
- 非法 JSON 修复一次，仍失败或超时/虚构引用 → 规则首选行动并标记 rule_fallback。
"""

from __future__ import annotations

import hashlib
import json
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import EventType, TaskStatus, TaskType
from app.infrastructure.curriculum import get_course_data
from app.infrastructure.llm.gateway import LLMGateway, build_gateway
from app.infrastructure.models import (
    Evidence,
    Goal,
    LLMUsage,
    PathDecision,
    Plan,
    Student,
    Task,
)
from app.infrastructure.repositories import events as events_repo
from app.infrastructure.repositories import learning as learning_repo
from app.infrastructure.repositories import plans as plans_repo
from app.services import planner as planner_service

TASK_MINUTES = planner_service.TASK_MINUTES
SYSTEM_PROMPT = (
    "你是初中数学路径决策 Agent。只输出 JSON："
    "{action, target_id, reason, evidence_ids:[...]}。"
    "action/target_id 必须与 legal_actions 中某一项完全一致；不新增行动，不编造证据。"
)


# ---------------------------------------------------------------------------
# 规则层：候选行动生成（权威集合）
# ---------------------------------------------------------------------------

def _concept_title(concept_id: str) -> str:
    data = get_course_data().concept(concept_id)
    return data["title"] if data else concept_id


def build_candidates(db: Session, *, student: Student, goal: Goal, plan: Plan) -> list[dict]:
    """规则产生此刻的合法路径行动候选（顺序即规则优先级）。"""
    candidates: list[dict] = []
    _, nodes, _ = planner_service._classify(db, student, goal)
    tasks = [
        t
        for t in plans_repo.tasks_for_goal(db, student.id, goal.id)
        if t.status in (TaskStatus.queued.value, TaskStatus.active.value)
    ]
    budget_left = student.daily_minutes - sum(t.estimated_minutes for t in tasks)

    # 1) 复习到期优先（§9.2）
    for task in tasks:
        node = nodes.get(task.concept_id)
        if task.type == TaskType.review.value and node is not None and node.status == "review_due":
            candidates.append(
                {
                    "action": "schedule_review",
                    "target_id": task.id,
                    "reason_code": "review_due",
                    "label": f"先做「{node.title}」复习题",
                    "message": f"「{node.title}」已到复习时间，先做一道复习题巩固。",
                }
            )

    # 2) 重复错误 → 在进入后续任务前先补测（排除偶发失误）
    for cid, node in nodes.items():
        if node.status not in ("developing", "needs_support") or not node.eligible:
            continue
        errors = planner_service.distinct_error_exercises(db, student.id, cid)
        if errors < 2:
            continue
        already = plans_repo.open_task_for_concept(
            db, student.id, goal.id, cid, [TaskType.practice.value]
        )
        if already is not None or budget_left < TASK_MINUTES:
            continue
        candidates.append(
            {
                "action": "insert_probe",
                "target_id": cid,
                "reason_code": "repeated_error",
                "label": f"先做 1 道「{node.title}」符号辨析补测",
                "message": f"「{node.title}」近期在 {errors} 道不同题出现错误，先补测确认是否稳定。",
            }
        )

    # 3) 按计划继续下一任务
    next_task = planner_service.next_startable_task(db, student.id, goal.id, plan)
    if next_task is not None:
        type_label = {"lesson": "讲解", "practice": "练习", "review": "复习"}.get(next_task.type, "任务")
        candidates.append(
            {
                "action": "continue_task",
                "target_id": next_task.id,
                "reason_code": "next_in_plan",
                "label": f"按计划继续「{_concept_title(next_task.concept_id)}」{type_label}",
                "message": f"按当前计划继续「{_concept_title(next_task.concept_id)}」{type_label}。",
            }
        )

    return candidates


def _state_signature(db: Session, *, student: Student, goal: Goal, plan: Plan, candidates: list[dict]) -> dict:
    _, nodes, _ = planner_service._classify(db, student, goal)
    return {
        "policy_version": planner_service.POLICY_VERSION,
        "plan_version": plan.version,
        "mastery": {cid: node.status for cid, node in sorted(nodes.items())},
        "candidates": candidates,
    }


def _state_hash(signature: dict) -> str:
    return hashlib.sha256(
        json.dumps(signature, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


# ---------------------------------------------------------------------------
# LLM 选择与校验
# ---------------------------------------------------------------------------

def _build_payload(signature: dict, candidates: list[dict]) -> dict:
    return {
        "task": (
            "为学生的下一步学习路径选择一个行动。只输出 JSON："
            "{action, target_id, reason, evidence_ids:[...]}。"
            "action/target_id 必须与候选集合中某一项完全一致；reason 用一句学生可读的话说明安排依据。"
        ),
        "state": {
            "policy_version": signature["policy_version"],
            "plan_version": signature["plan_version"],
            "mastery": signature["mastery"],
        },
        "legal_actions": candidates,
    }


def _validate_parsed(
    db: Session, *, student_id: str, parsed: object, candidates: list[dict]
) -> tuple[dict | None, str | None]:
    """selected 必须与候选集合的 action+target_id 完全匹配；evidence 归属校验。"""
    if not isinstance(parsed, dict):
        return None, "decision_not_object"
    action = parsed.get("action")
    target_id = parsed.get("target_id")
    entry = next(
        (c for c in candidates if c["action"] == action and c.get("target_id") == target_id),
        None,
    )
    if entry is None:
        return None, f"action_target_not_legal:{action}:{target_id}"

    evidence_ids = parsed.get("evidence_ids") or []
    if not isinstance(evidence_ids, list):
        return None, "evidence_ids_not_list"
    for eid in evidence_ids:
        exists = db.execute(
            select(Evidence.id).where(Evidence.id == eid, Evidence.student_id == student_id)
        ).scalar_one_or_none()
        if exists is None:
            return None, f"fabricated_evidence_id:{eid}"

    reason = parsed.get("reason") or parsed.get("student_message") or entry.get("message", "")
    return (
        {
            "action": action,
            "target_id": target_id,
            "reason_code": entry["reason_code"],
            "reason": (reason if isinstance(reason, str) else entry.get("message", "")).strip()[:160],
            "evidence_ids": [e for e in evidence_ids][:8],
            "label": entry.get("label", ""),
        },
        None,
    )


# ---------------------------------------------------------------------------
# 执行器（规则代码，LLM 不直接写状态）
# ---------------------------------------------------------------------------

def _execute(
    db: Session,
    *,
    student: Student,
    goal: Goal,
    plan: Plan,
    selected: dict,
    correlation_id: str | None,
) -> tuple[bool, Plan, Task | None]:
    """执行合法行动。返回 (changed, 生效计划, 当前任务)。"""
    action = selected["action"]
    if action in ("continue_task", "schedule_review"):
        task = plans_repo.task_owned(db, student.id, selected["target_id"])
        return False, plan, task

    if action == "insert_probe":
        cid = selected["target_id"]
        if plans_repo.open_task_for_concept(db, student.id, goal.id, cid, [TaskType.practice.value]):
            return False, plan, None
        new_plan = Plan(
            student_id=student.id,
            goal_id=goal.id,
            version=plan.version + 1,
            ordered_concept_ids=plan.ordered_concept_ids,
            node_status_snapshot=plan.node_status_snapshot or {},
            active_task_ids=[],
            reason_code=f"path_decision:{selected['reason_code']}",
            evidence_ids=selected.get("evidence_ids", []),
            policy_version=plan.policy_version,
        )
        db.add(new_plan)
        db.flush()
        task = plans_repo.add_task(
            db,
            student_id=student.id,
            goal_id=goal.id,
            plan_version=new_plan.version,
            concept_id=cid,
            type=TaskType.practice.value,
            status=TaskStatus.queued.value,
            estimated_minutes=TASK_MINUTES,
        )
        new_plan.active_task_ids = [
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
                "plan_id": new_plan.id,
                "version": new_plan.version,
                "reason_code": new_plan.reason_code,
                "previous_version": plan.version,
                "created_task_ids": [task.id],
                "source": "path_decision",
            },
            correlation_id=correlation_id,
        )
        return True, new_plan, task

    return False, plan, None


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def decide_path(
    db: Session,
    *,
    student: Student,
    goal: Goal,
    gateway: LLMGateway | None = None,
    correlation_id: str | None = None,
) -> tuple[dict, PathDecision]:
    started = time.monotonic()
    plan = plans_repo.latest_plan(db, student.id, goal.id)
    plan_before = {"version": plan.version, "ordered_concept_ids": plan.ordered_concept_ids} if plan else None

    candidates = build_candidates(db, student=student, goal=goal, plan=plan) if plan else []
    signature = (
        _state_signature(db, student=student, goal=goal, plan=plan, candidates=candidates)
        if plan
        else {"policy_version": planner_service.POLICY_VERSION, "plan_version": 0, "mastery": {}, "candidates": []}
    )
    state_hash = _state_hash(signature)

    selected: dict | None = None
    planner_source = "rule_fallback"
    model_id: str | None = None
    fallback_reason: str | None = None
    status = "unchanged"

    if not candidates:
        status = "no_legal_action"
        selected = {
            "action": "no_legal_action",
            "target_id": None,
            "reason_code": "no_legal_action",
            "reason": "当前没有可调整的合法行动，保持现状。",
            "evidence_ids": [],
            "label": "暂无可选行动",
        }
    else:
        gw = gateway or build_gateway()
        outcome = gw.decide(payload=_build_payload(signature, candidates), system=SYSTEM_PROMPT)
        _record_usage(db, student_id=student.id, outcome=outcome)
        validation_error: str | None = outcome.error

        if outcome.parsed is not None:
            selected, validation_error = _validate_parsed(
                db, student_id=student.id, parsed=outcome.parsed, candidates=candidates
            )
            if selected is None:
                # 伪造 action/target/evidence 或 Schema 不合法 → 修复一次
                outcome2 = gw.decide(
                    payload=_build_payload(signature, candidates),
                    validation_error=validation_error,
                    system=SYSTEM_PROMPT,
                )
                _record_usage(db, student_id=student.id, outcome=outcome2)
                if outcome2.parsed is not None:
                    selected, validation_error = _validate_parsed(
                        db, student_id=student.id, parsed=outcome2.parsed, candidates=candidates
                    )
                    if selected is not None:
                        model_id = outcome2.usage.get("model_id")
                else:
                    validation_error = outcome2.error
            else:
                model_id = outcome.usage.get("model_id")

        if selected is not None and model_id is not None:
            planner_source = "llm"
        else:
            fallback_reason = validation_error or outcome.error or "model_unavailable"
            first = candidates[0]
            selected = {
                "action": first["action"],
                "target_id": first.get("target_id"),
                "reason_code": first["reason_code"],
                "reason": first.get("message", ""),
                "evidence_ids": [],
                "label": first.get("label", ""),
            }

    changed = False
    current_task = None
    effective_plan = plan
    if status != "no_legal_action" and selected is not None:
        changed, effective_plan, current_task = _execute(
            db,
            student=student,
            goal=goal,
            plan=plan,
            selected=selected,
            correlation_id=correlation_id,
        )
        status = "adjusted" if changed else "unchanged"

    duration_ms = int((time.monotonic() - started) * 1000)
    decision = PathDecision(
        student_id=student.id,
        goal_id=goal.id,
        status=status,
        candidate_actions=candidates,
        selected_action=selected or {},
        reason=(selected or {}).get("reason", ""),
        evidence_ids=(selected or {}).get("evidence_ids", []),
        policy_version=planner_service.POLICY_VERSION,
        planner_source=planner_source,
        model_id=model_id,
        fallback_reason=fallback_reason,
        duration_ms=duration_ms,
        plan_version_before=plan.version if plan else 0,
        plan_version_after=effective_plan.version if effective_plan else 0,
        changed=changed,
        input_state_hash=state_hash,
    )
    db.add(decision)
    db.flush()

    plan_after = (
        {"version": effective_plan.version, "ordered_concept_ids": effective_plan.ordered_concept_ids}
        if effective_plan
        else None
    )
    data = {
        "decision_id": decision.id,
        "status": status,
        "candidate_actions": candidates,
        "selected_action": selected or {},
        "reason": (selected or {}).get("reason", ""),
        "evidence_ids": (selected or {}).get("evidence_ids", []),
        "policy_version": planner_service.POLICY_VERSION,
        "model_id": model_id,
        "planner_source": planner_source,
        "fallback_reason": fallback_reason,
        "duration_ms": duration_ms,
        "plan_before": plan_before,
        "plan_after": plan_after,
        "changed": changed,
        "current_task": (
            {
                "id": current_task.id,
                "concept_id": current_task.concept_id,
                "type": current_task.type,
                "status": current_task.status,
                "estimated_minutes": current_task.estimated_minutes,
                "version": current_task.version,
            }
            if current_task is not None
            else None
        ),
        "input_state_hash": state_hash,
    }
    return data, decision


def latest_decision(db: Session, student_id: str, goal_id: str) -> PathDecision | None:
    return db.execute(
        select(PathDecision)
        .where(PathDecision.student_id == student_id, PathDecision.goal_id == goal_id)
        .order_by(PathDecision.created_at.desc())
    ).scalars().first()


def list_decisions(db: Session, student_id: str, goal_id: str, limit: int = 20) -> list[PathDecision]:
    return list(
        db.execute(
            select(PathDecision)
            .where(PathDecision.student_id == student_id, PathDecision.goal_id == goal_id)
            .order_by(PathDecision.created_at.desc())
            .limit(limit)
        ).scalars().all()
    )


def _record_usage(db: Session, *, student_id: str, outcome) -> None:
    for attempt in outcome.attempts:
        db.add(
            LLMUsage(
                student_id=student_id,
                purpose="path_decision",
                model_id=outcome.usage.get("model_id"),
                prompt_tokens=attempt.get("prompt_tokens", 0),
                completion_tokens=attempt.get("completion_tokens", 0),
                ok=attempt.get("error") is None,
            )
        )
    db.flush()
