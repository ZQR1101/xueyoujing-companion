"""基于真实学习事件的激励投影；不修改评分、掌握度或学习计划。"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.models import Attempt, Evidence, Event, Exercise, MasteryState, Question, Student, Task

POINTS = {"answer_graded": 2, "task_completed": 5, "reflection_saved": 3, "session_paused": 0}

# id、名称、说明、指标、门槛。全部进度都从持久化学习事实计算，不接受前端自报。
BADGE_DEFS = [
    ("first_evidence", "第一条证据", "完成首次可计入的独立作答", "independent", 1),
    ("task_runner", "任务完成者", "完成 3 项学习任务", "tasks", 3),
    ("three_day_streak", "三日坚持", "连续学习 3 天", "streak", 3),
    ("transfer_thinker", "迁移思考", "独立完成 1 道迁移题", "transfer", 1),
    ("reflection_record", "反思记录", "保存 1 次学习反思", "reflections", 1),
    ("stable_review", "稳定复习", "完成 3 项复习任务", "reviews", 3),
    ("five_day_streak", "五日坚持", "连续学习 5 天", "streak", 5),
    ("seven_day_streak", "七日坚持", "连续学习 7 天", "streak", 7),
    ("fourteen_day_streak", "十四日坚持", "连续学习 14 天", "streak", 14),
    ("first_breakthrough", "首次突破", "形成 1 次有效掌握度更新", "mastery_updates", 1),
    ("one_mastered", "知识点掌握", "有 1 个知识点达到已掌握", "mastered", 1),
    ("three_mastered", "三点掌握", "有 3 个知识点达到已掌握", "mastered", 3),
    ("chapter_explorer", "章节探索者", "完成 6 项学习任务", "tasks", 6),
    ("path_follower", "路径践行者", "完成 5 项计划任务", "tasks", 5),
    ("careful_correction", "认真订正", "完成 3 次先错后对的订正", "corrections", 3),
    ("independent_thinker", "独立思考", "完成 3 次可计入的独立作答", "independent", 3),
    ("low_hint_challenge", "少提示挑战", "在零提示或一级提示下完成 3 次有效作答", "low_hint", 3),
    ("transfer_challenge", "迁移挑战", "独立完成 3 道迁移题", "transfer", 3),
    ("reflection_habit", "反思习惯", "保存 3 次有学习事件支撑的反思", "reflections", 3),
    ("learning_planner", "学习规划师", "沿当前计划完成 7 项任务", "tasks", 7),
    ("morning_study", "早起研习", "在上午 9 点前学习 3 天", "morning", 3),
    ("focus_moment", "专注时刻", "单次会话持续学习至少 20 分钟", "focus", 1),
    ("progress_trace", "进步轨迹", "积累 5 次有效掌握度更新", "mastery_updates", 5),
    ("persistent_growth", "坚持成长", "累计完成 20 项学习任务", "tasks", 20),
    ("study_milestone", "研习里程碑", "累计完成 100 次可计入的独立作答", "independent", 100),
]


def _streak(events: list[Event]) -> int:
    days = {e.created_at.date() for e in events if e.type in POINTS and POINTS[e.type] > 0}
    cursor = date.today()
    # 当天尚未学习时，从最近一个学习日计算已形成的连续记录。
    if cursor not in days and cursor - timedelta(days=1) in days:
        cursor -= timedelta(days=1)
    count = 0
    while cursor in days:
        count += 1
        cursor -= timedelta(days=1)
    return count


def _metrics(db: Session, student_id: str, events: list[Event]) -> tuple[dict[str, int], dict[str, list[str]]]:
    valid_event_ids = {event.id for event in events}
    evidences = db.execute(
        select(Evidence).where(Evidence.student_id == student_id, Evidence.eligible.is_(True))
    ).scalars().all()
    evidences = [evidence for evidence in evidences if evidence.event_id in valid_event_ids]
    attempt_ids = [e.attempt_id for e in evidences]
    attempts = db.execute(select(Attempt).where(Attempt.id.in_(attempt_ids))).scalars().all() if attempt_ids else []
    attempt_by_id = {a.id: a for a in attempts}
    exercise_ids = [a.exercise_id for a in attempts]
    exercises = db.execute(select(Exercise).where(Exercise.id.in_(exercise_ids))).scalars().all() if exercise_ids else []
    exercise_by_id = {x.id: x for x in exercises}
    question_ids = [x.question_id for x in exercises]
    questions = db.execute(select(Question).where(Question.id.in_(question_ids))).scalars().all() if question_ids else []
    question_by_id = {q.id: q for q in questions}

    completed_tasks = db.execute(
        select(Task).where(Task.student_id == student_id, Task.status == "completed")
    ).scalars().all()
    mastered = db.execute(
        select(MasteryState).where(MasteryState.student_id == student_id, MasteryState.status == "mastered")
    ).scalars().all()

    by_exercise: dict[str, list[Attempt]] = defaultdict(list)
    all_attempts = db.execute(
        select(Attempt).where(Attempt.student_id == student_id).order_by(Attempt.created_at)
    ).scalars().all()
    for attempt in all_attempts:
        by_exercise[attempt.exercise_id].append(attempt)
    corrections = sum(1 for rows in by_exercise.values() if rows[0].grade != "correct" and rows[-1].grade == "correct")

    eligible_event_ids = [e.event_id for e in evidences if e.event_id]
    transfer_event_ids, low_hint_event_ids = [], []
    for evidence in evidences:
        attempt = attempt_by_id.get(evidence.attempt_id)
        exercise = exercise_by_id.get(attempt.exercise_id) if attempt else None
        question = question_by_id.get(exercise.question_id) if exercise else None
        if question and question.purpose == "transfer":
            transfer_event_ids.append(evidence.event_id)
        if attempt and attempt.hint_level_at_submission <= 1:
            low_hint_event_ids.append(evidence.event_id)

    task_events = [e for e in events if e.type == "task_completed"]
    completed_task_ids = {t.id for t in completed_tasks}
    task_event_ids = [e.id for e in task_events if e.payload.get("task_id") in completed_task_ids]
    review_task_ids = {t.id for t in completed_tasks if t.type == "review"}
    review_event_ids = [e.id for e in task_events if e.payload.get("task_id") in review_task_ids]
    reflection_event_ids = [e.id for e in events if e.type == "reflection_saved"]
    mastery_event_ids = eligible_event_ids
    morning_events = [e for e in events if POINTS.get(e.type, 0) > 0 and e.created_at.hour < 9]
    morning_days = sorted({e.created_at.date() for e in morning_events})

    sessions: dict[str, list[Event]] = defaultdict(list)
    for event in events:
        if event.session_id and POINTS.get(event.type, 0) > 0:
            sessions[event.session_id].append(event)
    focus_event_ids = []
    for rows in sessions.values():
        rows.sort(key=lambda e: e.created_at)
        if len(rows) >= 2 and (rows[-1].created_at - rows[0].created_at).total_seconds() >= 1200:
            focus_event_ids = [e.id for e in rows]
            break

    evidence_event_by_id = {evidence.id: evidence.event_id for evidence in evidences}
    mastered_event_ids = [
        evidence_event_by_id[evidence_id]
        for mastery in mastered
        for evidence_id in (mastery.recent_evidence_ids or [])
        if evidence_id in evidence_event_by_id
    ]
    mastered_supported = sum(
        1 for mastery in mastered
        if any(evidence_id in evidence_event_by_id for evidence_id in (mastery.recent_evidence_ids or []))
    )
    metrics = {
        "independent": len(evidences), "tasks": len(task_event_ids), "streak": _streak(events),
        "transfer": len(transfer_event_ids), "reflections": len(reflection_event_ids),
        "reviews": len(review_event_ids), "mastery_updates": len(evidences), "mastered": mastered_supported,
        "corrections": corrections, "low_hint": len(low_hint_event_ids),
        "morning": len(morning_days), "focus": 1 if focus_event_ids else 0,
    }
    sources = {
        "independent": eligible_event_ids, "tasks": task_event_ids, "streak": [e.id for e in events if POINTS.get(e.type, 0) > 0],
        "transfer": transfer_event_ids, "reflections": reflection_event_ids, "reviews": review_event_ids,
        "mastery_updates": mastery_event_ids,
        "mastered": mastered_event_ids,
        "corrections": [e.id for e in events if e.type in {"answer_submitted", "answer_graded"}],
        "low_hint": low_hint_event_ids, "morning": [e.id for e in morning_events], "focus": focus_event_ids,
    }
    return metrics, sources


def overview(db: Session, student: Student) -> dict:
    events = db.execute(select(Event).where(Event.student_id == student.id).order_by(Event.created_at)).scalars().all()
    points = sum(POINTS.get(e.type, 0) for e in events)
    metrics, sources = _metrics(db, student.id, events)
    catalog = []
    for badge_id, name, reason, metric, target in BADGE_DEFS:
        current = metrics[metric]
        acquired = current >= target
        catalog.append({
            "id": badge_id, "name": name, "reason": reason, "acquired": acquired,
            "progress": {"current": min(current, target), "target": target},
            # 未达成时不暗示已经获得；达成后只返回数据库中确实存在的事件/证据 ID。
            "evidence_event_ids": sorted(set(sources[metric])) if acquired else [],
        })
    badges = [badge for badge in catalog if badge["acquired"]]
    level = 1 + points // 30
    streak = metrics["streak"]
    message = "先完成一道独立练习，积累第一条有效学习证据。" if points == 0 else (
        f"你已连续学习 {streak} 天，今天再完成一个小任务即可保持节奏。" if streak
        else "每一次真实作答都会让学习路径更准确。"
    )
    claimed = {e.payload.get("reward_id") for e in events if e.type == "reward_claimed"}
    rewards = []
    if metrics["tasks"] >= 1 and "task_first" not in claimed:
        rewards.append({"reward_id": "task_first", "name": "首项任务完成", "cost_points": 0})
    if streak >= 3 and "streak_3" not in claimed:
        rewards.append({"reward_id": "streak_3", "name": "三日坚持奖励", "cost_points": 0})
    return {
        "points": points, "level": level, "level_name": f"研习者 Lv.{level}", "streak_days": streak,
        "badges": badges, "badge_catalog": catalog, "badge_total": len(catalog), "earned_badge_count": len(badges),
        "rewards": rewards, "next_reward": {"points_needed": max(0, 30 - (points % 30)), "name": "下一阶段研习徽章"},
        "message": message,
    }


def leaderboard(db: Session, limit: int = 10) -> list[dict]:
    students = db.execute(select(Student)).scalars().all()
    rows = []
    for student in students:
        events = db.execute(select(Event).where(Event.student_id == student.id)).scalars().all()
        score = sum(POINTS.get(e.type, 0) for e in events)
        rows.append({"student_id": student.id, "display_name": f"学习者{str(student.id)[-4:]}", "points": score})
    rows.sort(key=lambda row: (-row["points"], row["student_id"]))
    return [{"rank": index + 1, **row} for index, row in enumerate(rows[:limit])]
