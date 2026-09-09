from fastapi import APIRouter, Request
# Motivation routes are part of the live T14-D surface.
from app.api.deps import CurrentStudent, DbSession
from app.api.envelope import envelope
from app.services.motivation import overview, leaderboard
from app.api.idempotency import run_idempotent
from app.domain.errors import ResourceNotFound
from app.infrastructure.models import Event
router=APIRouter(prefix="/api/v1", tags=["motivation"])
@router.get("/me/motivation")
def get_motivation(request: Request, db: DbSession, student: CurrentStudent):
    return envelope(request, overview(db, student))

@router.get("/motivation/leaderboard")
def get_leaderboard(request: Request, db: DbSession, student: CurrentStudent):
    return envelope(request, {"entries": leaderboard(db)})

@router.post("/me/motivation/rewards/{reward_id}/claim")
def claim_reward(request: Request, db: DbSession, student: CurrentStudent, reward_id: str):
    def execute(s):
        data = overview(s, student)
        reward = next((r for r in data["rewards"] if r["reward_id"] == reward_id), None)
        if reward is None: raise ResourceNotFound("奖励不存在、未达成或已领取")
        s.add(Event(student_id=student.id, type="reward_claimed", payload={"reward_id":reward_id,"name":reward["name"]}))
        s.flush()
        return {"reward_id":reward_id,"name":reward["name"],"claimed":True}, None, None
    return run_idempotent(db, student_id=student.id, request=request, payload={"reward_id":reward_id}, execute=execute)
