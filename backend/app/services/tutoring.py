"""辅导循环服务（§10 状态机 + 分级提示）。

- 提示 0～4 级：1 提醒概念；2 指出关键关系；3 用不同数字的类比；
  4 提供下一步局部过程。每次只返回一层，连续请求逐级推进（A15：不一次倾倒）。
- 查看解析：返回标准答案与逐级讲解，solution_seen=true；其后原题作答不再
  产生独立掌握证据（由证据管线判定），必须以新题验证（A16）。
- 解析内容 = 标准答案 + 分级提示拼装（课程包暂无独立解析字段，见 T06 记录备注）。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import EventType, SessionStatus, TaskStatus
from app.domain.errors import IllegalState, VersionConflict
from app.infrastructure.curriculum import get_course_data
from app.infrastructure.models import Exercise, Question, Student, Task
from app.infrastructure.repositories import events as events_repo
from app.infrastructure.repositories import learning as learning_repo
from app.infrastructure.repositories import plans as plans_repo
from app.infrastructure.repositories import questions as questions_repo
from app.services import planner as planner_service

MAX_HINT_LEVEL = 4


def _task_of(db: Session, exercise: Exercise) -> Task:
    if exercise.task_id is None:
        raise IllegalState("该练习不属于学习任务")
    task = db.get(Task, exercise.task_id)
    if task is None:
        raise IllegalState("任务不存在")
    return task


def show_hint(
    db: Session, *, student_id: str, exercise: Exercise, expected_version: int
) -> dict:
    if expected_version != exercise.version:
        raise VersionConflict("练习状态已更新，请刷新后继续")
    if exercise.status != "open":
        raise IllegalState("该练习已关闭，无需提示")

    question = questions_repo.question_owned(db, exercise.question_id)
    hints = question.private_hints or []
    if exercise.hint_level >= MAX_HINT_LEVEL or exercise.hint_level >= len(hints):
        raise IllegalState("提示已到最高级")
    next_level = exercise.hint_level + 1

    learning_repo.patch_exercise_guarded(
        db, exercise.id, expected_version, hint_level=next_level
    )
    db.refresh(exercise)

    events_repo.record_event(
        db,
        student_id=student_id,
        type=EventType.hint_shown,
        payload={
            "exercise_id": exercise.id,
            "question_id": question.id,
            "level": next_level,
        },
    )
    return {
        "level": next_level,
        "hint": hints[next_level - 1],
        "exercise_version": exercise.version,
    }


def show_solution(
    db: Session, *, student_id: str, exercise: Exercise, expected_version: int
) -> dict:
    if expected_version != exercise.version:
        raise VersionConflict("练习状态已更新，请刷新后继续")
    if exercise.status != "open":
        raise IllegalState("该练习已关闭")

    question = questions_repo.question_owned(db, exercise.question_id)
    course = get_course_data()
    concept = course.concept(question.primary_concept_id)

    if question.type == "mcq":
        key = question.private_answer["value"]
        option_text = next(
            (o["text"] for o in question.public_options if o["key"] == key), key
        )
        answer_display = f"{key}. {option_text}"
    else:
        answer_display = str(question.private_answer["value"])

    # 合同 v1.2 R6：完整解析独立存储，不再用分级提示拼装
    solution_text = (question.private_solution or "").strip()
    if not solution_text:
        solution_text = "。".join(question.private_hints or [])

    learning_repo.patch_exercise_guarded(
        db, exercise.id, expected_version, solution_seen=True
    )
    db.refresh(exercise)

    events_repo.record_event(
        db,
        student_id=student_id,
        type=EventType.solution_viewed,
        payload={"exercise_id": exercise.id, "question_id": question.id},
    )
    return {
        "solution_seen": True,
        "answer": answer_display,
        "solution": solution_text,
        "concept_title": concept["title"] if concept else question.primary_concept_id,
        "note": "查看解析后，本题不再产生独立掌握证据；请用新题验证。",
        "exercise_version": exercise.version,
    }


def _task_dto(task: Task) -> dict:
    return {
        "id": task.id,
        "concept_id": task.concept_id,
        "type": task.type,
        "status": task.status,
        "estimated_minutes": task.estimated_minutes,
        "version": task.version,
    }


def _complete_task(db: Session, task: Task, correlation_id: str | None) -> None:
    if task.status != TaskStatus.completed.value:
        plans_repo.set_task_status(db, task, TaskStatus.completed.value)
        events_repo.record_event(
            db,
            student_id=task.student_id,
            type=EventType.task_completed,
            payload={"task_id": task.id, "concept_id": task.concept_id, "type": task.type},
            correlation_id=correlation_id,
        )


def _pick_task_question(db: Session, student_id: str, task: Task) -> Question | None:
    used = learning_repo.student_attempted_question_ids(db, student_id)
    candidates = questions_repo.screening_candidates_for_concept(db, task.concept_id, used)
    if task.type == "review":
        review_first = [q for q in candidates if q.purpose == "review"]
        pool = review_first + [q for q in candidates if q.purpose != "review"]
    else:
        practice_first = [q for q in candidates if q.purpose in ("practice", "screening")]
        pool = practice_first + [q for q in candidates if q.purpose not in ("practice", "screening")]
    return pool[0] if pool else None


def start_next(
    db: Session,
    *,
    student: Student,
    session,
    goal,
    expected_version: int,
    correlation_id: str | None = None,
) -> tuple[dict, int, dict | None]:
    """开始下一个任务；已有未完成任务/未关闭练习时优先恢复（§9.2 规则 1）。

    paused 状态允许直接开始：start-next 本身即隐式恢复（与诊断的隐式恢复一致），
    避免前端残留旧状态时点击出现 400。
    """
    if expected_version != session.version:
        raise VersionConflict("学习状态已更新，请刷新后继续")
    if session.status == SessionStatus.completed.value:
        raise IllegalState("本轮研习已结束；切换演示身份或新建目标可重新开始")
    if session.status == SessionStatus.diagnosing.value:
        raise IllegalState("诊断进行中，请先完成当前诊断题")

    plan = plans_repo.latest_plan(db, student.id, goal.id)
    if plan is None:
        raise IllegalState("尚未生成学习计划，请先完成诊断")

    open_rows = db.execute(
        select(Exercise).where(
            Exercise.student_id == student.id,
            Exercise.task_id.isnot(None),
            Exercise.status == "open",
        )
    ).scalars().all()
    if open_rows:
        exercise = open_rows[0]
        question = questions_repo.question_owned(db, exercise.question_id)
        task = _task_of(db, exercise)
        data = {
            "resumed": True,
            "task": _task_dto(task),
            "exercise": {
                "id": exercise.id,
                "status": exercise.status,
                "version": exercise.version,
                "hint_level": exercise.hint_level,
            },
            "question": public_question(question),
        }
        return data, session.version, None

    task = planner_service.next_startable_task(db, student.id, goal.id, plan)
    if task is None:
        raise IllegalState("计划内没有待办任务（预算或前置约束限制）")

    plans_repo.set_task_status(db, task, TaskStatus.active.value)

    if task.type == "lesson":
        from app.infrastructure.retrieval import retrieve_for_concept

        resources = retrieve_for_concept(get_course_data(), task.concept_id, top_k=1)
        resource = resources[0] if resources else None
        # 合同 v1.2 R7：呈现只记 lesson_presented，任务保持 active，等待学生确认
        events_repo.record_event(
            db,
            student_id=student.id,
            type=EventType.lesson_presented,
            payload={"task_id": task.id, "concept_id": task.concept_id},
            correlation_id=correlation_id,
        )
        planner_service.ensure_session_learning(db, session, session.version)
        data = {
            "resumed": False,
            "task": _task_dto(task),
            "content": {
                "concept_id": task.concept_id,
                "source_id": resource.source_id if resource else None,
                "title": resource.title if resource else task.concept_id,
                "excerpt": resource.excerpt if resource else "",
                "relevance_score": resource.relevance_score if resource else None,
            },
            "note": "确认理解后调用 POST /api/v1/tasks/{task_id}/acknowledge 完成任务。",
        }
        return data, session.version, None

    question = _pick_task_question(db, student.id, task)
    if question is None:
        from app.domain.errors import InsufficientItems

        raise InsufficientItems("题库无可用新题族，保留现有掌握估计")
    exercise = Exercise(student_id=student.id, task_id=task.id, question_id=question.id)
    db.add(exercise)
    db.flush()
    planner_service.ensure_session_learning(db, session, session.version)
    data = {
        "resumed": False,
        "task": _task_dto(task),
        "exercise": {
            "id": exercise.id,
            "status": exercise.status,
            "version": exercise.version,
            "hint_level": 0,
        },
        "question": public_question(question),
    }
    return data, session.version, None


def acknowledge_lesson(
    db: Session,
    *,
    student: Student,
    task: Task,
    expected_version: int,
    correlation_id: str | None = None,
) -> dict:
    """学生确认讲解完成（合同 v1.2 R7）：lesson_acknowledged → 任务闭环 task_completed。

    讲解本身不产生掌握证据；确认后任务才算完成并计入完成率。
    """
    if task.type != "lesson":
        raise IllegalState("只有讲解任务需要确认")
    if task.status not in (TaskStatus.active.value, TaskStatus.queued.value):
        raise IllegalState("该任务不在待确认状态")
    if expected_version != task.version:
        raise VersionConflict("任务状态已更新，请刷新后继续")

    events_repo.record_event(
        db,
        student_id=student.id,
        type=EventType.lesson_acknowledged,
        payload={"task_id": task.id, "concept_id": task.concept_id},
        correlation_id=correlation_id,
    )
    _complete_task(db, task, correlation_id)
    db.refresh(task)
    return _task_dto(task)


def public_question(question: Question) -> dict:
    from app.api.serializers import public_question_dto

    return public_question_dto(question)
