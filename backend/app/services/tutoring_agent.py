"""T12-B Tutor Agent 启发式辅导（思路分析 + 苏格拉底追问 + 辅导轨迹）。

- submit_thinking：学生提交思路/困惑 → LLM 结构化分析
  （feedback 温和反馈 / possible_problem 可能的问题 / socratic_question 追问）
  → Schema 校验失败修复一次 → 规则回退；全程不泄露答案与私有提示；
- tutoring_trace：作答/提示/解析/思路/反馈聚合为时间线（读接口零写入）；
- 思路分析不产生、不修改任何掌握证据（与 §7.1/T06 证据规则一致）；
- LLM 调用走既有网关（超时/用量/修复一次），规则层权威。
"""

from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import EventType
from app.domain.errors import IllegalState
from app.infrastructure.llm.gateway import LLMGateway, build_gateway
from app.infrastructure.models import (
    Event,
    Exercise,
    LLMUsage,
    MasteryState,
    Question,
    Student,
)
from app.infrastructure.repositories import events as events_repo
from app.infrastructure.repositories import learning as learning_repo

MAX_TEXT = 1000
SYSTEM_PROMPT = (
    "你是初中数学启发式辅导 Agent（苏格拉底式）。只输出 JSON："
    "{feedback: 一句温和反馈, possible_problem: 可能的问题（一句）, socratic_question: 一个追问}。"
    "绝不给出本题答案，不复述完整解题步骤。"
)


# ---------------------------------------------------------------------------
# 上下文（只含公开字段，不含答案/私有提示）
# ---------------------------------------------------------------------------

def _build_context(db: Session, *, student: Student, exercise: Exercise, text: str) -> dict:
    question = db.get(Question, exercise.question_id)
    attempts = learning_repo.attempts_for_exercise(db, exercise.id)
    mastery = db.execute(
        select(MasteryState).where(
            MasteryState.student_id == student.id,
            MasteryState.concept_id == question.primary_concept_id,
        )
    ).scalar_one_or_none()
    return {
        "question": {
            "prompt": question.prompt,
            "type": question.type,
            "difficulty": question.difficulty,
            "concept_title": question.primary_concept_id,
        },
        "attempt_summary": {
            "count": len(attempts),
            "last_grade": attempts[-1].grade if attempts else None,
            "last_answer": attempts[-1].answer if attempts else None,
        },
        "mastery": {
            "status": mastery.status if mastery else "unassessed",
            "estimate": mastery.estimate if mastery else None,
            "evidence_count": mastery.evidence_count if mastery else 0,
        },
        "hint_level": exercise.hint_level,
        "solution_seen": exercise.solution_seen,
        "student_thinking": text,
    }


def _build_payload(context: dict) -> dict:
    return {
        "task": (
            "你是初中数学启发式辅导 Agent（苏格拉底式）。学生刚提交了思路/困惑。只输出 JSON："
            "{feedback: 一句温和反馈, possible_problem: 可能的问题（一句）, "
            "socratic_question: 一个引导学生自己推进的追问}。"
            "绝不给出本题最终答案，不复述完整解题步骤，不评价学生能力。"
        ),
        "constraints": [
            "feedback/possible_problem/socratic_question 都必须是非空中文短句",
            "不得包含本题答案或可直接抄写的完整解式",
            "基于学生的思路与作答摘要，不臆造未提供的证据",
        ],
        "state": context,
        "legal_actions": [],  # 占位：网关 MockProvider 需要该键；本任务不提供教学行动
    }


# ---------------------------------------------------------------------------
# 校验与规则回退
# ---------------------------------------------------------------------------

def _validate_parsed(parsed: object) -> tuple[dict | None, str | None]:
    if not isinstance(parsed, dict):
        return None, "analysis_not_object"
    feedback = parsed.get("feedback")
    problem = parsed.get("possible_problem")
    socratic = parsed.get("socratic_question")
    for name, value in (("feedback", feedback), ("possible_problem", problem), ("socratic_question", socratic)):
        if not isinstance(value, str) or not value.strip():
            return None, f"{name}_missing"
    return (
        {
            "feedback": feedback.strip()[:160],
            "possible_problem": problem.strip()[:120],
            "socratic_question": socratic.strip()[:200],
        },
        None,
    )


def _rule_analysis(context: dict) -> dict:
    """规则回退：不依赖模型，也绝不泄露答案。"""
    last_grade = context["attempt_summary"]["last_grade"]
    hint_level = context["hint_level"]
    if last_grade == "incorrect":
        feedback = "这次还没有答对，我们先一起检查你的思路，不着急看答案。"
        problem = (
            "结合已用提示，关键步骤的对应关系还需要确认。"
            if hint_level > 0
            else "先重读题目条件，把每个条件对应到你的式子里。"
        )
        socratic = "你能否把题目中的每个条件，分别对应到你式子里的某一项？哪一条还没对上？"
    else:
        feedback = "思路已收到，我们继续核对关键步骤。"
        problem = "当前判断证据不足，先按题目条件逐条核对。"
        socratic = "你的式子里，哪个部分是直接从题目条件得到的？哪个还是假设？"
    return {"feedback": feedback, "possible_problem": problem, "socratic_question": socratic}


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def submit_thinking(
    db: Session,
    *,
    student: Student,
    exercise: Exercise,
    text: str,
    gateway: LLMGateway | None = None,
    correlation_id: str | None = None,
) -> dict:
    if exercise.student_id != student.id:
        from app.domain.errors import ResourceNotFound

        raise ResourceNotFound("题目不存在或不属于当前学生")
    if exercise.status != "open":
        raise IllegalState("题目已关闭，无需继续辅导")
    text = (text or "").strip()[:MAX_TEXT]
    if not text:
        from app.domain.errors import InvalidRequest

        raise InvalidRequest("思路内容不能为空")

    started = time.monotonic()
    context = _build_context(db, student=student, exercise=exercise, text=text)

    events_repo.record_event(
        db,
        student_id=student.id,
        type=EventType.thinking_submitted,
        payload={"exercise_id": exercise.id, "question_id": exercise.question_id, "text": text},
        correlation_id=correlation_id,
    )

    gw = gateway or build_gateway()
    outcome = gw.decide(payload=_build_payload(context), system=SYSTEM_PROMPT)
    _record_usage(db, student_id=student.id, outcome=outcome)
    validation_error: str | None = outcome.error

    parsed: dict | None = None
    model_id: str | None = None
    if outcome.parsed is not None:
        parsed, validation_error = _validate_parsed(outcome.parsed)
        if parsed is None:
            outcome2 = gw.decide(
                payload=_build_payload(context), validation_error=validation_error, system=SYSTEM_PROMPT
            )
            _record_usage(db, student_id=student.id, outcome=outcome2)
            if outcome2.parsed is not None:
                parsed, validation_error = _validate_parsed(outcome2.parsed)
                if parsed is not None:
                    model_id = outcome2.usage.get("model_id")
            else:
                validation_error = outcome2.error
        else:
            model_id = outcome.usage.get("model_id")

    planner_source = "llm" if parsed is not None and model_id is not None else "rule_fallback"
    fallback_reason = None
    if planner_source != "llm":
        fallback_reason = validation_error or outcome.error or "model_unavailable"
        parsed = _rule_analysis(context)

    events_repo.record_event(
        db,
        student_id=student.id,
        type=EventType.tutor_feedback,
        payload={
            "exercise_id": exercise.id,
            "question_id": exercise.question_id,
            **parsed,
            "planner_source": planner_source,
            "model_id": model_id,
            "fallback_reason": fallback_reason,
        },
        correlation_id=correlation_id,
    )

    return {
        "exercise_id": exercise.id,
        **parsed,
        "planner_source": planner_source,
        "model_id": model_id,
        "fallback_reason": fallback_reason,
        "hint_level": exercise.hint_level,
        "duration_ms": int((time.monotonic() - started) * 1000),
    }


def latest_feedback(db: Session, student_id: str, exercise_id: str) -> Event | None:
    rows = db.execute(
        select(Event)
        .where(Event.student_id == student_id, Event.type == EventType.tutor_feedback.value)
        .order_by(Event.created_at.desc())
        .limit(20)
    ).scalars().all()
    for row in rows:
        if (row.payload or {}).get("exercise_id") == exercise_id:
            return row
    return None


# ---------------------------------------------------------------------------
# 辅导轨迹（读接口零写入）
# ---------------------------------------------------------------------------

def tutoring_trace(db: Session, *, student: Student, exercise: Exercise) -> dict:
    if exercise.student_id != student.id:
        from app.domain.errors import ResourceNotFound

        raise ResourceNotFound("题目不存在或不属于当前学生")

    timeline: list[dict] = []
    timeline.append(
        {
            "type": "start",
            "time": exercise.created_at.isoformat() + "Z",
            "label": "开始审题",
        }
    )
    for attempt in learning_repo.attempts_for_exercise(db, exercise.id):
        timeline.append(
            {
                "type": "attempt",
                "time": attempt.created_at.isoformat() + "Z",
                "label": "提交答案，通过" if attempt.grade == "correct" else "提交答案，未通过",
                "answer": attempt.answer,
                "grade": attempt.grade,
            }
        )
    rows = db.execute(
        select(Event)
        .where(
            Event.student_id == student.id,
            Event.type.in_(
                [
                    EventType.hint_shown.value,
                    EventType.solution_viewed.value,
                    EventType.thinking_submitted.value,
                    EventType.tutor_feedback.value,
                ]
            ),
        )
        .order_by(Event.created_at)
    ).scalars().all()
    for row in rows:
        payload = row.payload or {}
        if payload.get("exercise_id") != exercise.id:
            continue
        if row.type == EventType.hint_shown.value:
            level = payload.get("level", 0)
            timeline.append(
                {
                    "type": "hint",
                    "time": row.created_at.isoformat() + "Z",
                    "label": f"使用{'一二三四'[level - 1] if 0 < level <= 4 else level}级提示",
                    "level": level,
                }
            )
        elif row.type == EventType.solution_viewed.value:
            timeline.append({"type": "solution", "time": row.created_at.isoformat() + "Z", "label": "查看完整解析"})
        elif row.type == EventType.thinking_submitted.value:
            timeline.append(
                {
                    "type": "thinking",
                    "time": row.created_at.isoformat() + "Z",
                    "label": "提交思路",
                    "excerpt": (payload.get("text") or "")[:40],
                }
            )
        elif row.type == EventType.tutor_feedback.value:
            timeline.append(
                {
                    "type": "feedback",
                    "time": row.created_at.isoformat() + "Z",
                    "label": "Tutor Agent 反馈/追问",
                    "possible_problem": payload.get("possible_problem"),
                    "planner_source": payload.get("planner_source"),
                }
            )

    timeline.sort(key=lambda item: item["time"])
    current_label = "等待修改后重新提交" if exercise.status == "open" else "本题已完成"
    return {
        "exercise_id": exercise.id,
        "status": exercise.status,
        "hint_level": exercise.hint_level,
        "solution_seen": exercise.solution_seen,
        "timeline": timeline,
        "current": {"label": current_label},
    }


def _record_usage(db: Session, *, student_id: str, outcome) -> None:
    for attempt in outcome.attempts:
        db.add(
            LLMUsage(
                student_id=student_id,
                purpose="tutor_thinking",
                model_id=outcome.usage.get("model_id"),
                prompt_tokens=attempt.get("prompt_tokens", 0),
                completion_tokens=attempt.get("completion_tokens", 0),
                ok=attempt.get("error") is None,
            )
        )
    db.flush()
