"""目标端点（§12：POST /goals；replan/path/tasks 自 T05）。"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query, Request
from sqlalchemy import select

from app.api.deps import CurrentStudent, DbSession
from app.api.dto import CreateGoal, ReplanGoal
from app.api.idempotency import run_idempotent
from app.api.serializers import goal_dto, session_dto
from app.domain.errors import ResourceNotFound, VersionConflict
from app.infrastructure.models import Goal, LearningSession, Plan, Student
from app.infrastructure.repositories import goals as goals_repo
from app.infrastructure.repositories import plans as plans_repo
from app.services import goals as goals_service
from app.services import planner as planner_service

router = APIRouter(prefix="/api/v1", tags=["goals"])


@router.post("/goals")
def create_goal(
    request: Request, db: DbSession, student: CurrentStudent, payload: CreateGoal
) -> dict:
    def execute(session) -> tuple[dict, int, None]:  # noqa: ANN001
        goal, learning_session = goals_service.create_goal(
            session,
            student,
            course_id=payload.course_id,
            target_concept_ids=payload.target_concept_ids,
            daily_minutes=payload.daily_minutes,
            correlation_id=getattr(request.state, "trace_id", None),
        )
        data = {"goal": goal_dto(goal), "session": session_dto(learning_session)}
        return data, learning_session.version, None

    return run_idempotent(
        db,
        student_id=student.id,
        request=request,
        payload=payload.model_dump(),
        execute=execute,
    )


@router.post("/goals/{goal_id}/replan")
def replan_goal(
    request: Request, db: DbSession, student: CurrentStudent, goal_id: str, payload: ReplanGoal
) -> dict:
    def execute(session) -> tuple[dict, int, None]:  # noqa: ANN001
        goal = goals_repo.goal_owned(session, student.id, goal_id)
        latest = plans_repo.latest_plan(session, student.id, goal.id)
        current_version = latest.version if latest else 0
        if payload.expected_version != current_version:
            raise VersionConflict("计划已更新，请刷新后重试")
        plan, changed = planner_service.generate_plan(
            session,
            student=student,
            goal=goal,
            reason_code=payload.reason,
            correlation_id=getattr(request.state, "trace_id", None),
        )
        data = {
            "plan": {
                "id": plan.id,
                "version": plan.version,
                "ordered_concept_ids": plan.ordered_concept_ids,
                "reason_code": plan.reason_code,
                "policy_version": plan.policy_version,
                "active_task_ids": plan.active_task_ids,
            },
            "changed": changed,
        }
        return data, plan.version, None

    return run_idempotent(
        db,
        student_id=student.id,
        request=request,
        payload=payload.model_dump(),
        execute=execute,
    )


@router.get("/goals/{goal_id}/path")
def get_path(
    request: Request, db: DbSession, student: CurrentStudent, goal_id: str
) -> dict:
    goal = goals_repo.goal_owned(db, student.id, goal_id)
    data = planner_service.path_view(db, student=student, goal=goal)
    from app.api.envelope import envelope

    version = data["plan"]["version"] if data["plan"] else 0
    return envelope(request, data, resource_version=version)


@router.get("/goals/{goal_id}/plans")
def get_plan_history(
    request: Request, db: DbSession, student: CurrentStudent, goal_id: str
) -> dict:
    from app.api.envelope import envelope

    goal = goals_repo.goal_owned(db, student.id, goal_id)
    rows = list(
        db.execute(
            select(Plan)
            .where(
                Plan.student_id == student.id,
                Plan.goal_id == goal.id,
            )
            .order_by(Plan.version.desc())
        ).scalars().all()
    )
    data = {
        "plans": [
            {
                "id": p.id,
                "version": p.version,
                "reason_code": p.reason_code,
                "policy_version": p.policy_version,
                "ordered_concept_ids": p.ordered_concept_ids,
                "evidence_ids": p.evidence_ids,
                "created_at": p.created_at.isoformat() + "Z",
            }
            for p in rows
        ]
    }
    version = rows[0].version if rows else 0
    return envelope(request, data, resource_version=version)


@router.get("/goals/{goal_id}/tasks")
def get_tasks(
    request: Request,
    db: DbSession,
    student: CurrentStudent,
    goal_id: str,
    date: str | None = Query(default=None, description="YYYY-MM-DD，按学生时区；缺省为今天"),
) -> dict:
    from app.api.envelope import envelope

    goal = goals_repo.goal_owned(db, student.id, goal_id)
    latest = plans_repo.latest_plan(db, student.id, goal.id)

    tz = ZoneInfo(student.timezone)
    if date:
        try:
            target_date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError as exc:
            from app.domain.errors import InvalidRequest

            raise InvalidRequest("date 格式应为 YYYY-MM-DD") from exc
    else:
        target_date = datetime.now(timezone.utc).astimezone(tz).date()

    tasks = plans_repo.tasks_for_goal(db, student.id, goal.id)
    items = []
    for task in tasks:
        local_date = task.created_at.replace(tzinfo=timezone.utc).astimezone(tz).date()
        if local_date != target_date:
            continue
        items.append(
            {
                "id": task.id,
                "concept_id": task.concept_id,
                "type": task.type,
                "status": task.status,
                "estimated_minutes": task.estimated_minutes,
                "version": task.version,
                "plan_version": task.plan_version,
            }
        )
    pending_minutes = sum(
        t["estimated_minutes"] for t in items if t["status"] in ("queued", "active")
    )
    data = {
        "date": target_date.isoformat(),
        "budget_minutes": student.daily_minutes,
        "pending_minutes": pending_minutes,
        "within_budget": pending_minutes <= student.daily_minutes,
        "tasks": items,
        "plan_version": latest.version if latest else 0,
    }
    version = latest.version if latest else 0
    return envelope(request, data, resource_version=version)
