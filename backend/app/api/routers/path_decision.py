"""T11-B LLM 路径决策端点。

- POST /goals/{goal_id}/path-decision：生成决策（幂等；expected_version=当前计划版本，
  版本冲突返回 409，客户端以 GET 获取最新计划，不覆盖其他版本）；
- GET  /goals/{goal_id}/path-decision：最近一次决策（只读）；
- GET  /goals/{goal_id}/path-decisions：决策轨迹列表（查询接口）。
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.deps import CurrentStudent, DbSession
from app.api.dto import PathDecisionRequest
from app.api.envelope import envelope
from app.api.idempotency import run_idempotent
from app.domain.errors import VersionConflict
from app.infrastructure.repositories import goals as goals_repo
from app.infrastructure.repositories import plans as plans_repo
from app.services import path_decision as decision_service

router = APIRouter(prefix="/api/v1", tags=["path-decision"])


def _decision_data(decision) -> dict:  # noqa: ANN001
    return {
        "decision_id": decision.id,
        "status": decision.status,
        "candidate_actions": decision.candidate_actions,
        "selected_action": decision.selected_action,
        "reason": decision.reason,
        "evidence_ids": decision.evidence_ids,
        "policy_version": decision.policy_version,
        "model_id": decision.model_id,
        "planner_source": decision.planner_source,
        "fallback_reason": decision.fallback_reason,
        "duration_ms": decision.duration_ms,
        "plan_version_before": decision.plan_version_before,
        "plan_version_after": decision.plan_version_after,
        "changed": decision.changed,
        "input_state_hash": decision.input_state_hash,
        "created_at": decision.created_at.isoformat() + "Z",
    }


@router.post("/goals/{goal_id}/path-decision")
def create_path_decision(
    request: Request,
    db: DbSession,
    student: CurrentStudent,
    goal_id: str,
    payload: PathDecisionRequest,
) -> dict:
    def execute(session) -> tuple[dict, int, None]:  # noqa: ANN001
        goal = goals_repo.goal_owned(session, student.id, goal_id)
        latest = plans_repo.latest_plan(session, student.id, goal.id)
        current_version = latest.version if latest else 0
        if payload.expected_version != current_version:
            # 版本冲突：返回最新计划版本号，客户端以 GET 获取最新计划，不覆盖其他版本
            raise VersionConflict(
                f"路径已更新（当前 v{current_version}），请刷新后重试"
            )
        data, decision = decision_service.decide_path(
            session,
            student=student,
            goal=goal,
            correlation_id=getattr(request.state, "trace_id", None),
        )
        return data, decision.plan_version_after, None

    return run_idempotent(
        db,
        student_id=student.id,
        request=request,
        payload=payload.model_dump(),
        execute=execute,
    )


@router.get("/goals/{goal_id}/path-decision")
def get_path_decision(
    request: Request, db: DbSession, student: CurrentStudent, goal_id: str
) -> dict:
    goal = goals_repo.goal_owned(db, student.id, goal_id)
    decision = decision_service.latest_decision(db, student.id, goal.id)
    if decision is None:
        from app.domain.errors import ResourceNotFound

        raise ResourceNotFound("尚未生成路径决策")
    latest = plans_repo.latest_plan(db, student.id, goal.id)
    data = _decision_data(decision)
    data["current_plan_version"] = latest.version if latest else 0
    return envelope(request, data, resource_version=latest.version if latest else 0)


@router.get("/goals/{goal_id}/path-decisions")
def list_path_decisions(
    request: Request, db: DbSession, student: CurrentStudent, goal_id: str
) -> dict:
    goal = goals_repo.goal_owned(db, student.id, goal_id)
    rows = decision_service.list_decisions(db, student.id, goal.id)
    latest = plans_repo.latest_plan(db, student.id, goal.id)
    data = {"decisions": [_decision_data(r) for r in rows]}
    return envelope(request, data, resource_version=latest.version if latest else 0)
