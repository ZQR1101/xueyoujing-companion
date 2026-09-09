"""Coordinator（§5/§9.4）：合法行动集合由规则产生，LLM 只在集合内选择。

- 校验：action ∈ 合法集合；target 归属与阶段合法；evidence_ids 必须真实属于该学生。
- 结构化输出失败最多修复一次，仍失败 → 规则回退（planner_source=rule_fallback）。
- 模型参与选择时 planner_source=llm；mock 提供者 model_id=mock（模拟模式可见标记）。
- Coordinator 不自行编造答案或掌握分数；LLM 调用在事务外由 Gateway 完成（本服务只落库）。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import SessionStatus
from app.domain.errors import IllegalState, VersionConflict
from app.domain.next_action import NextActionType, build_next_action
from app.infrastructure.llm.gateway import build_gateway
from app.infrastructure.models import Decision, Evidence, Goal, LLMUsage, LearningSession, Student, Task
from app.infrastructure.repositories import learning as learning_repo
from app.infrastructure.repositories import plans as plans_repo
from app.services import memory as memory_service
from app.services import planner as planner_service

DECISION_ACTIONS = {
    "ask_clarification",
    "present_lesson",
    "assign_practice",
    "offer_hint",
    "assign_transfer",
    "schedule_review",
    "finish_session",
}


def legal_actions(db: Session, *, student: Student, session: LearningSession, goal: Goal) -> list[dict]:
    """规则产生此刻的合法行动集合（A05 的约束来源）。"""
    actions: list[dict] = []

    open_exercise = None
    if session.status == SessionStatus.learning.value:
        open_exercise = db.execute(
            select_session_open_exercise(student.id, goal.id)
        ).scalar_one_or_none()

    if open_exercise is not None:
        actions.append(
            {
                "action": "offer_hint",
                "target_id": open_exercise.id,
                "reason_code": "open_exercise",
                "message": "这道题还没完成，需要的话我可以再给一点提示。",
            }
        )
        wrong_attempt = db.execute(
            _open_exercise_wrong_attempt(open_exercise.id)
        ).scalar_one_or_none()
        if wrong_attempt is not None:
            actions.append(
                {
                    "action": "assign_transfer",
                    "target_id": open_exercise.id,
                    "reason_code": "repeated_error",
                    "message": "换一道同类的新题试试，检验一下是不是真的掌握了。",
                }
            )

    plan = plans_repo.latest_plan(db, student.id, goal.id)
    if plan is not None and session.status in (
        SessionStatus.ready.value,
        SessionStatus.learning.value,
    ):
        task = planner_service.next_startable_task(db, student.id, goal.id, plan)
        if task is not None:
            if task.type == "lesson":
                actions.append(
                    {
                        "action": "present_lesson",
                        "target_id": task.id,
                        "reason_code": "next_in_plan",
                        "message": f"接下来学习「{task.concept_id}」的讲解，我先把内容给你。",
                    }
                )
            elif task.type == "review":
                actions.append(
                    {
                        "action": "schedule_review",
                        "target_id": task.id,
                        "reason_code": "review_due",
                        "message": "有一个知识点到复习时间了，先做一道复习题。",
                    }
                )
            else:
                actions.append(
                    {
                        "action": "assign_practice",
                        "target_id": task.id,
                        "reason_code": "next_in_plan",
                        "message": "来做一道练习题，检验刚才的内容。",
                    }
                )

    actions.append(
        {
            "action": "finish_session",
            "target_id": None,
            "reason_code": "student_request",
            "message": "今天可以先到这里，进度已经保存，随时回来继续。",
        }
    )
    return actions


def select_session_open_exercise(student_id: str, goal_id: str):
    from sqlalchemy import select

    from app.infrastructure.models import Exercise

    return (
        select(Exercise)
        .join(LearningSession, LearningSession.goal_id == goal_id)
        .where(
            Exercise.student_id == student_id,
            Exercise.task_id.isnot(None),
            Exercise.status == "open",
        )
        .order_by(Exercise.created_at)
        .limit(1)
    )


def _open_exercise_wrong_attempt(exercise_id: str):
    from sqlalchemy import text

    return text(
        """
        SELECT a.id FROM attempts a
        WHERE a.exercise_id = :eid AND a.grade = 'incorrect'
        LIMIT 1
        """
    ).bindparams(eid=exercise_id)


def _validate_decision(
    db: Session,
    *,
    student_id: str,
    parsed: dict | None,
    legal: list[dict],
) -> tuple[dict | None, str | None]:
    """返回 (规范化决策, 校验错误)。决策字段以规则集合为准（规则权威）。"""
    if not isinstance(parsed, dict):
        return None, "decision_not_object"
    action = parsed.get("action")
    if action not in DECISION_ACTIONS:
        return None, f"unknown_action:{action}"
    entry = next((a for a in legal if a["action"] == action), None)
    if entry is None:
        return None, f"action_not_legal:{action}"

    evidence_ids = parsed.get("evidence_ids") or []
    if not isinstance(evidence_ids, list):
        return None, "evidence_ids_not_list"
    for eid in evidence_ids:
        exists = db.execute(
            select(Evidence.id).where(Evidence.id == eid, Evidence.student_id == student_id)
        ).scalar_one_or_none()
        if exists is None:
            return None, f"evidence_not_found:{eid}"

    target_id = entry.get("target_id")
    model_target = parsed.get("target_id")
    if model_target not in (None, target_id):
        return None, f"target_mismatch:{model_target}"

    return (
        {
            "action": action,
            "target_id": target_id,
            "reason_code": parsed.get("reason_code") or entry.get("reason_code", "llm_choice"),
            "evidence_ids": [e for e in evidence_ids],
            "student_message": parsed.get("student_message") or entry.get("message", ""),
        },
        None,
    )


def _record_usage(db: Session, *, student_id: str, outcome) -> None:
    for attempt in outcome.attempts:
        db.add(
            LLMUsage(
                student_id=student_id,
                purpose="teaching_decision",
                model_id=outcome.usage.get("model_id"),
                prompt_tokens=attempt.get("prompt_tokens", 0),
                completion_tokens=attempt.get("completion_tokens", 0),
                ok=attempt.get("error") is None,
            )
        )
    db.flush()


def _next_action_for(decision: dict) -> dict | None:
    action = decision["action"]
    target = decision.get("target_id")
    if action == "offer_hint" or action == "assign_transfer":
        return build_next_action(NextActionType.retry_exercise, target)
    if action in ("present_lesson", "assign_practice", "schedule_review"):
        return build_next_action(NextActionType.start_task, target)
    if action == "finish_session":
        return build_next_action(NextActionType.show_result)
    return None


def send_message(
    db: Session,
    *,
    student: Student,
    session: LearningSession,
    goal: Goal,
    text: str,
    expected_version: int,
    correlation_id: str | None = None,
) -> tuple[dict, int, dict | None]:
    if expected_version != session.version:
        raise VersionConflict("学习状态已更新，请刷新后继续")
    if session.status == SessionStatus.paused.value:
        raise IllegalState("会话已暂停，请先 resume")
    if session.status == SessionStatus.completed.value:
        raise IllegalState("会话已结束")
    if session.status == SessionStatus.diagnosing.value:
        raise IllegalState("诊断进行中，先完成当前诊断题")

    legal = legal_actions(db, student=student, session=session, goal=goal)
    context = memory_service.build_context(
        db, student_id=student.id, session=session, goal=goal, task=None
    )
    payload = {
        "message": text,
        "context": context,
        "legal_actions": legal,
    }

    gateway = build_gateway()
    outcome = gateway.decide(payload=payload)
    _record_usage(db, student_id=student.id, outcome=outcome)

    decision = None
    model_ok = False
    final_error: str | None = None

    if outcome.parsed is None:
        # JSON 层失败（网关内部已含初始+修复一次）→ 直接规则回退
        final_error = outcome.error or "model_unavailable"
    else:
        decision, error = _validate_decision(
            db, student_id=student.id, parsed=outcome.parsed, legal=legal
        )
        if decision is not None:
            model_ok = True
        else:
            # JSON 合法但行动/证据/目标不合法 → 修复一次（§9.4）
            outcome2 = gateway.decide(payload=payload, validation_error=error)
            _record_usage(db, student_id=student.id, outcome=outcome2)
            decision, error2 = _validate_decision(
                db, student_id=student.id, parsed=outcome2.parsed, legal=legal
            )
            if decision is not None:
                model_ok = True
            else:
                final_error = error2 or error

    if model_ok and decision is not None:
        planner_source = "llm"
        fallback_reason = None
        model_id = outcome.usage.get("model_id", "mock")
        reply = decision.get("student_message") or "我们继续。"
    else:
        first = legal[0]
        decision = {
            "action": first["action"],
            "target_id": first.get("target_id"),
            "reason_code": "rule_fallback",
            "evidence_ids": [],
            "student_message": first.get("message", ""),
        }
        planner_source = "rule_fallback"
        fallback_reason = final_error or "model_unavailable"
        model_id = outcome.usage.get("model_id")
        reply = decision["student_message"] or "先按当前计划继续。"

    decision_row = Decision(
        student_id=student.id,
        session_id=session.id,
        action=decision["action"],
        reason_code=decision["reason_code"],
        evidence_ids=decision["evidence_ids"],
        input_state_version=session.version,
        planner_source=planner_source,
        model_id=model_id,
        fallback_reason=fallback_reason,
    )
    db.add(decision_row)
    db.flush()

    # 合同 v1.2 R8：finish_session 真实闭环——决策与业务状态一致
    session_completed = False
    if decision["action"] == "finish_session":
        learning_repo.bump_learning_session_version(db, session.id, session.version)
        db.refresh(session)
        session.status = SessionStatus.completed.value
        session_completed = True

    data = {
        "reply": reply,
        "decision": {
            "id": decision_row.id,
            "action": decision["action"],
            "target_id": decision.get("target_id"),
            "reason_code": decision["reason_code"],
            "evidence_ids": decision["evidence_ids"],
            "planner_source": planner_source,
            "model_id": model_id,
            "fallback_reason": fallback_reason,
        },
        "legal_actions": legal,
        "session_status": session.status,
        "session_completed": session_completed,
    }
    return data, session.version, _next_action_for(decision)
