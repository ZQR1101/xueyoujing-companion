"""T14-B 学习反思：只从真实事件/作答产生小结和可追溯 L2 记忆。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.errors import IllegalState, ResourceNotFound
from app.infrastructure.llm.gateway import build_gateway
from app.infrastructure.models import Attempt, Evidence, Event, Exercise, Goal, LearningReflection, LearningSession, LLMUsage, MemoryFact, Plan, Question, RagTrace, Student, Task

VALID = {"active", "superseded", "disputed", "invalidated"}

def _owned_session(db: Session, student_id: str, session_id: str) -> tuple[LearningSession, Goal]:
    session = db.get(LearningSession, session_id)
    if not session or session.student_id != student_id:
        raise ResourceNotFound("学习会话不存在或不属于当前学生")
    goal = db.get(Goal, session.goal_id)
    if not goal or goal.student_id != student_id:
        raise ResourceNotFound("课程目标不存在或不属于当前学生")
    return session, goal

def _attempt_rows(db: Session, student_id: str, goal: Goal):
    return db.execute(select(Attempt, Exercise, Question, Task).join(Exercise, Attempt.exercise_id == Exercise.id).join(Question, Exercise.question_id == Question.id).outerjoin(Task, Exercise.task_id == Task.id).where(Attempt.student_id == student_id, Question.course_id == goal.course_id).order_by(Attempt.created_at)).all()

def _event_id(db: Session, student_id: str, session_id: str, attempt: Attempt) -> str | None:
    # grading event is the authoritative evidence event; never fabricate an id.
    ev = db.execute(select(Event).where(Event.student_id == student_id, Event.session_id == session_id, Event.type.in_(["answer_graded", "answer_submitted"]), Event.payload["attempt_id"].as_string() == attempt.id).order_by(Event.created_at.desc())).scalars().first()
    return ev.id if ev else None

def _facts(db: Session, student_id: str, session_id: str, goal: Goal):
    independent, assisted, uncertain = {}, {}, {}
    for attempt, exercise, question, task in _attempt_rows(db, student_id, goal):
        eid = _event_id(db, student_id, session_id, attempt)
        if not eid: continue
        key = question.primary_concept_id
        # Evidence eligibility is the authoritative independent-first/family-dedup result.
        evidence = db.execute(select(Evidence).where(Evidence.student_id == student_id, Evidence.attempt_id == attempt.id, Evidence.eligible.is_(True))).scalars().first()
        independent_first = attempt.grade == "correct" and evidence is not None
        if independent_first:
            independent.setdefault(key, []).append(eid)
        elif attempt.grade == "correct":
            assisted.setdefault(key, []).append(eid)
        elif attempt.grade != "correct":
            uncertain.setdefault(key, []).append(eid)
    return independent, assisted, uncertain


def _session_signals(db: Session, student_id: str, session_id: str, goal: Goal) -> dict:
    errors: dict[str, int] = {}
    hints: dict[str, int] = {}
    exercise_ids: set[str] = set()
    concepts: set[str] = set()
    for attempt, exercise, question, _task in _attempt_rows(db, student_id, goal):
        if not _event_id(db, student_id, session_id, attempt):
            continue
        exercise_ids.add(exercise.id)
        concepts.add(question.primary_concept_id)
        if attempt.error_code:
            errors[attempt.error_code] = errors.get(attempt.error_code, 0) + 1
        level = str(attempt.hint_level_at_submission)
        hints[level] = hints.get(level, 0) + 1
    traces = []
    if exercise_ids:
        rows = db.execute(select(RagTrace).where(
            RagTrace.student_id == student_id,
            RagTrace.exercise_id.in_(exercise_ids),
        ).order_by(RagTrace.created_at)).scalars().all()
        traces = [{
            "trace_id": row.id, "status": row.status,
            "source_ids": [source.get("source_id") for source in (row.final_sources or []) if isinstance(source, dict) and source.get("source_id")],
        } for row in rows]
    return {
        "error_type_counts": errors,
        "hint_level_counts": hints,
        "rag_usage": traces,
        "session_exercise_count": len(exercise_ids),
        "session_concept_ids": sorted(concepts),
    }

def _recommendation(db: Session, student_id: str, goal: Goal, evidence_ids: list[str]) -> dict:
    plan = db.execute(select(Plan).where(Plan.student_id == student_id, Plan.goal_id == goal.id).order_by(Plan.version.desc())).scalars().first()
    tasks = [] if not plan else db.execute(select(Task).where(Task.student_id == student_id, Task.goal_id == goal.id, Task.id.in_(plan.active_task_ids), Task.status.in_(["queued", "active"])).order_by(Task.created_at)).scalars().all()
    if not tasks: return {"status":"no_available_task", "plan_version": plan.version if plan else None, "items": []}
    t = tasks[0]
    student = db.get(Student, student_id)
    budget = student.daily_minutes if student else 120
    return {"status":"ok", "plan_version":plan.version, "items":[{"concept_id":t.concept_id,"task_type":t.type,"reason":"当前有效计划中的未完成任务。","estimated_minutes":min(t.estimated_minutes, budget),"source_evidence_ids":evidence_ids}]}


def _validate_generated(parsed: dict, independent: dict, supported: dict, allowed_ids: set[str]) -> tuple[dict | None, str | None]:
    """模型只能润色规则结论；知识点归类和证据集合不能被模型扩张。"""
    if not isinstance(parsed, dict):
        return None, "reflection_not_object"
    required = {"learned", "still_uncertain", "evidence_summary", "learning_characteristics"}
    if not required.issubset(parsed):
        return None, "reflection_missing_fields"
    if not isinstance(parsed["learned"], list) or not isinstance(parsed["still_uncertain"], list) or not isinstance(parsed["learning_characteristics"], list) or not isinstance(parsed["evidence_summary"], dict):
        return None, "reflection_invalid_shape"
    forbidden = ("完全掌握", "彻底掌握", "高置信度掌握")
    for section in ("learned", "still_uncertain", "learning_characteristics"):
        for item in parsed[section]:
            if not isinstance(item, dict) or not isinstance(item.get("evidence_event_ids"), list):
                return None, "reflection_invalid_item"
            ids = item["evidence_event_ids"]
            if any(not isinstance(x, str) or x not in allowed_ids for x in ids):
                return None, "reflection_unknown_evidence_event_id"
            if any(word in str(item.get("statement", "")) for word in forbidden):
                return None, "reflection_forbidden_claim"
            if section in {"learned", "still_uncertain"} and item.get("concept_id") is not None and not ids:
                return None, "reflection_fact_missing_evidence_event_id"
            if section == "learned":
                concept_id = item.get("concept_id")
                if concept_id not in independent or not set(ids).issubset(set(independent[concept_id])):
                    return None, "reflection_independent_claim_not_supported"
            elif section == "still_uncertain" and item.get("concept_id") is not None:
                concept_id = item["concept_id"]
                if concept_id not in supported or not set(ids).issubset(set(supported[concept_id])):
                    return None, "reflection_uncertain_claim_not_supported"
    return parsed, None


def _write_memories(db: Session, *, student_id: str, goal: Goal, session: LearningSession, items: list[dict]) -> None:
    for item in items:
        ids = item["evidence_event_ids"]
        if not ids or not item.get("concept_id"):
            continue
        old = db.execute(select(MemoryFact).where(
            MemoryFact.student_id == student_id, MemoryFact.course_id == goal.course_id,
            MemoryFact.concept_id == item["concept_id"], MemoryFact.type == "reflection_fact",
            MemoryFact.status == "active",
        ).order_by(MemoryFact.created_at.desc())).scalars().first()
        if old:
            old.status = "superseded"
        db.add(MemoryFact(
            student_id=student_id, course_id=goal.course_id, concept_id=item["concept_id"],
            type="reflection_fact", content=item["statement"], evidence_event_ids=ids,
            status="active", version=(old.version + 1 if old else 1),
            supersedes_id=old.id if old else None, source_session_id=session.id,
        ))
    db.flush()

def generate(db: Session, *, student_id: str, session_id: str, student_text: str | None = None, force_llm_failure: bool = False) -> dict:
    session, goal = _owned_session(db, student_id, session_id)
    independent, assisted, uncertain = _facts(db, student_id, session_id, goal)
    signals = _session_signals(db, student_id, session_id, goal)
    all_ids = sorted({x for group in (independent, assisted, uncertain) for ids in group.values() for x in ids})
    learned = [{"concept_id":c,"statement":"存在独立首答正确证据。","evidence_event_ids":ids} for c, ids in independent.items()]
    needs_work: dict[str, list[str]] = {}
    for group in (uncertain, assisted):
        for concept_id, ids in group.items():
            needs_work.setdefault(concept_id, []).extend(ids)
    still = [{"concept_id":c,"statement":"仍需用新题巩固。","evidence_event_ids":sorted(set(ids))} for c, ids in needs_work.items() if c not in independent]
    if not learned and not still: still = [{"concept_id":None,"statement":"暂时没有形成稳定结论。","evidence_event_ids":[]}]
    chars = []
    if assisted: chars.append({"statement":"本次有在提示或解析支持下完成的作答；不作为独立掌握。","evidence_event_ids":[x for v in assisted.values() for x in v]})
    if student_text:
        chars.append({"statement": f"学生反思：{student_text.strip()}", "evidence_event_ids": []})
    evidence_summary = {
        "event_ids": all_ids,
        "independent_count": sum(map(len, independent.values())),
        "assisted_count": sum(map(len, assisted.values())),
        **signals,
    }
    source = "reflection_rule_fallback"
    fallback_reason = "forced_llm_failure" if force_llm_failure else None
    if not force_llm_failure:
        outcome = build_gateway().decide(
            payload={
                "purpose": "learning_reflection", "allowed_evidence_event_ids": all_ids,
                "student_reflection": student_text or "",
                "rule_draft": {"learned": learned, "still_uncertain": still,
                               "evidence_summary": evidence_summary, "learning_characteristics": chars},
            },
            system="你是学习反思模块。只能依据规则草稿与真实事件润色，只输出 JSON。",
        )
        for attempt in outcome.attempts:
            db.add(LLMUsage(
                student_id=student_id, purpose="learning_reflection",
                model_id=outcome.usage.get("model_id"),
                prompt_tokens=attempt.get("prompt_tokens", 0), completion_tokens=attempt.get("completion_tokens", 0),
                ok=not bool(attempt.get("error")),
            ))
        supported: dict[str, list[str]] = {}
        for group in (independent, needs_work):
            for concept_id, ids in group.items():
                supported.setdefault(concept_id, []).extend(ids)
        supported = {concept_id: sorted(set(ids)) for concept_id, ids in supported.items()}
        parsed, validation_error = _validate_generated(outcome.parsed, independent, supported, set(all_ids)) if outcome.parsed is not None else (None, outcome.error)
        if parsed is not None:
            learned = parsed["learned"]
            still = parsed["still_uncertain"]
            chars = parsed["learning_characteristics"]
            source = "llm"
        else:
            fallback_reason = validation_error or "llm_invalid_output"
    try:
        rec = _recommendation(db, student_id, goal, all_ids)
    except Exception as exc:
        # Recommendation is optional: preserve the completed session/reflection.
        plan = db.execute(select(Plan).where(Plan.student_id == student_id, Plan.goal_id == goal.id).order_by(Plan.version.desc())).scalars().first()
        fallback_tasks = [] if not plan else db.execute(select(Task).where(Task.student_id == student_id, Task.goal_id == goal.id, Task.id.in_(plan.active_task_ids), Task.status.in_(["queued", "active"]))).scalars().all()
        rec = {"status": "plan_fallback", "plan_version": plan.version if plan else None,
               "items": [{"concept_id": t.concept_id, "task_type": t.type, "reason": "推荐生成失败，返回当前有效计划。", "estimated_minutes": t.estimated_minutes, "source_evidence_ids": all_ids} for t in fallback_tasks],
               "fallback_reason": type(exc).__name__}
    reflection = LearningReflection(student_id=student_id, course_id=goal.course_id, session_id=session.id, planner_source=source, fallback_reason=fallback_reason, learned=learned, still_uncertain=still, evidence_summary=evidence_summary, next_recommendation=rec, learning_characteristics=chars)
    db.add(reflection); db.flush()
    memory_write_status = "ok"
    try:
        with db.begin_nested():
            _write_memories(db, student_id=student_id, goal=goal, session=session, items=learned + still)
    except Exception as exc:
        memory_write_status = f"failed:{type(exc).__name__}"
    db.add(Event(student_id=student_id, session_id=session.id, type="reflection_saved", payload={"reflection_id":reflection.id,"event_ids":all_ids}))
    db.flush()
    result = serialize(reflection)
    result["summary"] = {
        "mastered_concept_ids": sorted(independent),
        "total_target": len(goal.target_concept_ids),
        "evidence_count_total": len(all_ids),
        "recent_evidence_ids": all_ids[-8:],
        "note": "学习结论仅依据真实作答事件生成。",
    }
    result["echo"] = student_text or ""
    result["memory_write_status"] = memory_write_status
    return result

def serialize(r: LearningReflection) -> dict:
    return {"reflection_id":r.id,"session_id":r.session_id,"course_id":r.course_id,"planner_source":r.planner_source,"fallback_reason":r.fallback_reason,"learned":r.learned,"still_uncertain":r.still_uncertain,"evidence_summary":r.evidence_summary,"next_recommendation":r.next_recommendation,"learning_characteristics":r.learning_characteristics,"created_at":r.created_at.isoformat()+"Z"}

def active_memories(db: Session, student_id: str, course_id: str, concept_id: str|None=None):
    q=select(MemoryFact).where(MemoryFact.student_id==student_id, MemoryFact.course_id==course_id, MemoryFact.status=="active")
    if concept_id: q=q.where(MemoryFact.concept_id==concept_id)
    return [memory_dict(x) for x in db.execute(q.order_by(MemoryFact.created_at.desc())).scalars()]

def memory_dict(x: MemoryFact): return {"memory_id":x.id,"student_id":x.student_id,"course_id":x.course_id,"concept_id":x.concept_id,"type":x.type,"content":x.content,"evidence_event_ids":x.evidence_event_ids,"status":x.status,"created_at":x.created_at.isoformat()+"Z","version":x.version,"supersedes_id":x.supersedes_id,"source_session_id":x.source_session_id}

def mark(db: Session, student_id: str, memory_id: str, status: str):
    x=db.get(MemoryFact,memory_id)
    if not x or x.student_id != student_id: raise ResourceNotFound("记忆不存在或不属于当前学生")
    if status not in {"disputed","invalidated","active"}: raise ValueError(status)
    if status == "active" and x.status not in {"disputed", "invalidated", "active"}:
        raise IllegalState("只能撤销学生纠错标记，不能恢复已被新版本替代的记忆")
    if status in {"disputed", "invalidated"} and x.status == "superseded":
        raise IllegalState("已被新版本替代的记忆不能作为当前记忆纠错")
    x.status=status; db.flush(); return memory_dict(x)

def chain(db: Session, student_id: str, memory_id: str):
    x=db.get(MemoryFact,memory_id)
    if not x or x.student_id != student_id: raise ResourceNotFound("记忆不存在或不属于当前学生")
    rows=[]
    while x: rows.append(memory_dict(x)); x=db.get(MemoryFact,x.supersedes_id) if x.supersedes_id else None
    return rows
