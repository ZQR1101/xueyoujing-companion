"""作答提交管线（§10/§11 短事务）。

诊断阶段：一次作答即关闭练习，next 走题序。
学习阶段（任务练习/复习）：
- 首答错误 → 练习保持 open，邀请说明思路并可请求提示（next_action=retry_exercise）；
- 原题答对（无论是否提示过）→ 关闭练习；若为原始题且任务未安排过迁移题，
  从**新题族**安排迁移题（next_action=next_question）；迁移题关闭后任务完成；
- 提示后原题重做、看解析后作答均不产生独立掌握证据（§7.1，由证据管线判定）；
- 有效证据改变 → 单次作答至多一次自动重规划（§9.3）。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import (
    AttemptGrade,
    EventType,
    ExerciseStatus,
    QuestionPurpose,
    SessionStatus,
    TaskStatus,
)
from app.domain.errors import IllegalState, InvalidRequest, VersionConflict
from app.domain.next_action import NextActionType, build_next_action
from app.domain.scoring import AnswerFormatError, grade_question
from app.infrastructure.models import (
    Assessment,
    Attempt,
    Exercise,
    Goal,
    LearningSession,
    Question,
    Student,
    Task,
)
from app.infrastructure.repositories import events as events_repo
from app.infrastructure.repositories import learning as learning_repo
from app.infrastructure.repositories import plans as plans_repo
from app.infrastructure.repositories import questions as questions_repo
from app.services import mastery as mastery_service
from app.services import planner as planner_service


def _session_for_assessment(db: Session, student_id: str, goal_id: str) -> LearningSession | None:
    return db.execute(
        select(LearningSession)
        .where(
            LearningSession.student_id == student_id,
            LearningSession.goal_id == goal_id,
        )
        .order_by(LearningSession.created_at.desc())
    ).scalars().first()


def _next_open_for_assessment(db: Session, assessment: Assessment) -> Exercise | None:
    for exercise in learning_repo.exercises_for_assessment(db, assessment):
        if exercise.status == ExerciseStatus.open.value:
            return exercise
    return None


def _task_has_transfer(db: Session, task: Task) -> bool:
    """任务是否已安排过迁移题（练习原始题之外的第二道题）。"""
    rows = db.execute(
        select(Exercise.id).where(Exercise.task_id == task.id)
    ).scalars().all()
    return len(rows) >= 2


def _create_transfer(db: Session, student: Student, task: Task) -> Exercise | None:
    """从新题族安排迁移题：排除该生已答题目，transfer 用途优先。"""
    used = learning_repo.student_attempted_question_ids(db, student.id)
    candidates = questions_repo.screening_candidates_for_concept(db, task.concept_id, used)
    transfer_first = [q for q in candidates if q.purpose == QuestionPurpose.transfer.value]
    pool = transfer_first + [q for q in candidates if q.purpose != QuestionPurpose.transfer.value]
    if not pool:
        return None
    exercise = Exercise(
        student_id=student.id,
        task_id=task.id,
        question_id=pool[0].id,
    )
    db.add(exercise)
    db.flush()
    return exercise


def _complete_task(db: Session, task: Task, correlation_id: str | None) -> None:
    if task.status != TaskStatus.completed.value:
        plans_repo.set_task_status(db, task, TaskStatus.completed.value)
        events_repo.record_event(
            db,
            student_id=task.student_id,
            type=EventType.task_completed,
            payload={
                "task_id": task.id,
                "concept_id": task.concept_id,
                "type": task.type,
            },
            correlation_id=correlation_id,
        )


def submit_attempt(
    db: Session,
    *,
    student: Student,
    exercise: Exercise,
    answer: str,
    expected_version: int,
    correlation_id: str | None = None,
) -> tuple[dict, int | None, dict | None]:
    """提交一次作答。返回 (data, resource_version, next_action)。"""
    if expected_version != exercise.version:
        # 版本冲突优先于状态检查（A09：并发双写时后到者收 409）
        raise VersionConflict("练习状态已更新，请刷新后继续")
    if exercise.status != ExerciseStatus.open.value:
        raise IllegalState("该练习已关闭")

    task: Task | None = None
    assessment: Assessment | None = None
    session: LearningSession | None = None
    if exercise.assessment_id is not None:
        assessment = learning_repo.assessment_owned(db, student.id, exercise.assessment_id)
        session = _session_for_assessment(db, student.id, assessment.goal_id)
        if session is None or session.status != SessionStatus.diagnosing.value:
            raise IllegalState("当前不在诊断阶段，无法提交该练习")
    elif exercise.task_id is not None:
        task = db.get(Task, exercise.task_id)
        if task is None:
            raise IllegalState("任务不存在")
        session = _session_for_assessment(db, student.id, task.goal_id)
        # 练习处于 open 即视为任务已开始；ready/paused（如诊断完成后回来、暂停后回来）
        # 都允许继续作答，避免状态机把学生卡死。
        if session is None or session.status not in (
            SessionStatus.learning.value,
            SessionStatus.ready.value,
            SessionStatus.paused.value,
        ):
            raise IllegalState("当前状态不能作答，请刷新后重试")

    question = questions_repo.question_owned(db, exercise.question_id)
    try:
        result = grade_question(question, answer)
    except AnswerFormatError as exc:
        raise InvalidRequest(f"答案格式错误：{exc}") from exc

    grade = AttemptGrade.correct if result.correct else AttemptGrade.incorrect
    prior_attempts = len(learning_repo.attempts_for_exercise(db, exercise.id))

    attempt = Attempt(
        exercise_id=exercise.id,
        student_id=student.id,
        answer=answer,
        grade=grade.value,
        hint_level_at_submission=exercise.hint_level,
        error_code=result.error_code,
    )
    db.add(attempt)
    db.flush()

    events_repo.record_event(
        db,
        student_id=student.id,
        type=EventType.answer_submitted,
        payload={
            "attempt_id": attempt.id,
            "exercise_id": exercise.id,
            "question_id": question.id,
        },
        session_id=session.id if session is not None else None,
        correlation_id=correlation_id,
    )

    evidence, before, after = mastery_service.apply_attempt_evidence(
        db,
        student_id=student.id,
        exercise=exercise,
        question=question,
        attempt=attempt,
        prior_attempts=prior_attempts,
        correlation_id=correlation_id,
    )

    transfer_available: bool | None = None

    if assessment is not None:
        # 诊断阶段：一次作答即关闭练习
        learning_repo.close_exercise_guarded(db, exercise.id, expected_version)
        db.refresh(exercise)
        learning_repo.bump_assessment_version(db, assessment.id, assessment.version)
        db.refresh(assessment)
        learning_repo.bump_learning_session_version(db, session.id, session.version)
        db.refresh(session)
        next_exercise = _next_open_for_assessment(db, assessment)
        next_action = (
            build_next_action(NextActionType.next_question, next_exercise.id)
            if next_exercise is not None
            else build_next_action(NextActionType.complete_assessment, assessment.id)
        )
    else:
        assert task is not None
        if grade != AttemptGrade.correct:
            # 首答错误：保持 open，邀请说明思路并重试（§10）
            next_action = build_next_action(NextActionType.retry_exercise, exercise.id)
        else:
            # 原题答对 → 关闭练习；练习任务安排新题族迁移验证
            learning_repo.close_exercise_guarded(db, exercise.id, expected_version)
            db.refresh(exercise)
            if task.type == "practice" and not _task_has_transfer(db, task):
                transfer = _create_transfer(db, student, task)
                if transfer is not None:
                    transfer_available = True
                    next_action = build_next_action(NextActionType.next_question, transfer.id)
                else:
                    transfer_available = False
                    next_action = None
                    _complete_task(db, task, correlation_id)
            else:
                next_action = None
                _complete_task(db, task, correlation_id)

        if evidence.eligible:
            goal = db.get(Goal, task.goal_id)
            if goal is not None:
                planner_service.generate_plan(
                    db,
                    student=student,
                    goal=goal,
                    reason_code="evidence_updated",
                    evidence_ids=[evidence.id],
                    correlation_id=correlation_id,
                )
        if session is not None:
            learning_repo.bump_learning_session_version(db, session.id, session.version)
            db.refresh(session)

    data = {
        "attempt": {
            "id": attempt.id,
            "exercise_id": exercise.id,
            "question_id": question.id,
            "answer": attempt.answer,
            "grade": attempt.grade,
            "hint_level_at_submission": attempt.hint_level_at_submission,
        },
        "mastery_delta": {
            "concept_id": question.primary_concept_id,
            "before": {"estimate": before.estimate, "status": before.status.value},
            "after": {"estimate": after.estimate, "status": after.status.value},
        },
        "evidence": {
            "id": evidence.id,
            "eligible": evidence.eligible,
            "exclusion_reason": evidence.exclusion_reason,
        },
        # §12：DTO 返回关联实体的各自版本（禁止混用全局与实体版本）
        "versions": {
            "exercise": exercise.version,
            "assessment": assessment.version if assessment is not None else None,
            "session": session.version if session is not None else None,
        },
        "transfer_available": transfer_available,
    }
    return data, exercise.version, next_action
