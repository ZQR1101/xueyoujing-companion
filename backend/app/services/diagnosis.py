"""诊断服务（§4.1 / §8）：选题、初筛流程、覆盖与完成。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.domain.enums import (
    AssessmentStatus,
    EventType,
    GoalStatus,
    MasteryStatus,
    SessionStatus,
)
from app.domain.errors import IllegalState, InsufficientItems, VersionConflict
from app.domain.mastery import projection_dto
from app.infrastructure.curriculum import get_course_data
from app.infrastructure.models import (
    Assessment,
    Exercise,
    Goal,
    LearningSession,
    Question,
    Student,
)
from app.infrastructure.repositories import events as events_repo
from app.infrastructure.repositories import learning as learning_repo
from app.infrastructure.repositories import questions as questions_repo
from app.services import planner as planner_service

MAX_DIAGNOSIS_QUESTIONS = 6


def _select_screening_questions(
    db: Session, goal: Goal
) -> list[Question]:
    """每个目标概念优先覆盖一题，按拓扑稳定排列；最多 6 题。"""
    course = get_course_data()
    topo = [cid for cid in course.topo_order if cid in set(goal.target_concept_ids)]
    already_attempted = learning_repo.student_attempted_question_ids(db, goal.student_id)

    selected: list[Question] = []
    for concept_id in topo:
        if len(selected) >= MAX_DIAGNOSIS_QUESTIONS:
            break
        excluded = already_attempted + [q.id for q in selected]
        candidates = questions_repo.screening_candidates_for_concept(
            db, concept_id, excluded
        )
        if candidates:
            selected.append(candidates[0])
    return selected


def start_diagnosis(
    db: Session,
    *,
    student: Student,
    session: LearningSession,
    goal: Goal,
    expected_version: int,
    correlation_id: str | None = None,
) -> tuple[Assessment, Exercise | None]:
    if goal.status != GoalStatus.active.value:
        raise IllegalState("目标已不在进行中")
    if expected_version != session.version:
        raise VersionConflict("学习状态已更新，请刷新后继续")

    existing = learning_repo.in_progress_assessment_for_goal(db, student.id, goal.id)
    if existing is not None:
        exercises = learning_repo.exercises_for_assessment(db, existing)
        open_exercises = [e for e in exercises if e.status == "open"]
        return existing, (open_exercises[0] if open_exercises else None)

    if session.status == SessionStatus.completed.value:
        raise IllegalState("会话已完成")

    selected = _select_screening_questions(db, goal)
    if not selected:
        raise InsufficientItems("题库无可用新题族，保留现有掌握估计")

    assessment = Assessment(
        student_id=student.id,
        goal_id=goal.id,
        status=AssessmentStatus.in_progress.value,
        question_ids=[q.id for q in selected],
    )
    db.add(assessment)
    db.flush()
    for question in selected:
        db.add(
            Exercise(
                student_id=student.id,
                assessment_id=assessment.id,
                question_id=question.id,
            )
        )
    db.flush()

    if session.status != SessionStatus.diagnosing.value:
        learning_repo.bump_learning_session_version(db, session.id, session.version)
        db.refresh(session)
        session.status = SessionStatus.diagnosing.value

    events_repo.record_event(
        db,
        student_id=student.id,
        session_id=session.id,
        type=EventType.diagnosis_started,
        payload={
            "assessment_id": assessment.id,
            "question_ids": assessment.question_ids,
        },
        correlation_id=correlation_id,
    )
    exercises = learning_repo.exercises_for_assessment(db, assessment)
    return assessment, (exercises[0] if exercises else None)


def next_open_exercise(
    db: Session, assessment: Assessment, after_exercise_id: str | None = None
) -> Exercise | None:
    """第一个 open 的练习；after_exercise_id 用于跳过语义（GET 不写状态）。"""
    exercises = learning_repo.exercises_for_assessment(db, assessment)
    if after_exercise_id:
        seen = False
        for exercise in exercises:
            if not seen:
                seen = exercise.id == after_exercise_id
                continue
            if exercise.status == "open":
                return exercise
        return None
    for exercise in exercises:
        if exercise.status == "open":
            return exercise
    return None


def complete_assessment(
    db: Session,
    *,
    student: Student,
    session: LearningSession,
    goal: Goal,
    assessment: Assessment,
    expected_version: int,
    correlation_id: str | None = None,
) -> dict:
    if assessment.status != AssessmentStatus.in_progress.value:
        raise IllegalState("诊断已完成或已放弃")
    if expected_version != assessment.version:
        raise VersionConflict("诊断状态已更新，请刷新后继续")

    exercises = learning_repo.exercises_for_assessment(db, assessment)
    attempted_concepts = set()
    for exercise in exercises:
        if learning_repo.attempts_for_exercise(db, exercise.id):
            question = questions_repo.question_owned(db, exercise.question_id)
            attempted_concepts.add(question.primary_concept_id)

    targets = list(goal.target_concept_ids)
    states = learning_repo.mastery_states_for_concepts(db, student.id, targets)
    snapshot = []
    for concept_id in targets:
        state = states.get(concept_id)
        if state is None:
            snapshot.append(
                {
                    "concept_id": concept_id,
                    "estimate": None,
                    "status": MasteryStatus.unassessed.value,
                    "evidence_count": 0,
                }
            )
        else:
            snapshot.append(
                {
                    "concept_id": concept_id,
                    "estimate": state.estimate,
                    "status": state.status,
                    "evidence_count": state.evidence_count,
                }
            )

    uncovered = [cid for cid in targets if cid not in attempted_concepts]
    assessment.coverage = {
        "assessed": [cid for cid in targets if cid in attempted_concepts],
        "unassessed": uncovered,
    }
    assessment.status = AssessmentStatus.completed.value
    learning_repo.bump_assessment_version(db, assessment.id, assessment.version)
    db.refresh(assessment)

    plan, _changed = planner_service.generate_plan(
        db,
        student=student,
        goal=goal,
        reason_code="diagnosis_completed",
        evidence_ids=[],
        correlation_id=correlation_id,
    )

    learning_repo.bump_learning_session_version(db, session.id, session.version)
    db.refresh(session)
    session.status = SessionStatus.ready.value

    return {
        "snapshot": snapshot,
        "uncovered_concept_ids": uncovered,
        "coverage": assessment.coverage,
        "plan": {
            "id": plan.id,
            "version": plan.version,
            "ordered_concept_ids": plan.ordered_concept_ids,
            "reason_code": plan.reason_code,
            "policy_version": plan.policy_version,
            "active_task_ids": plan.active_task_ids,
        },
    }
