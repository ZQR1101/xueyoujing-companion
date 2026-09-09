"""我的学情端点（只读）。"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.deps import CurrentStudent, DbSession
from app.api.envelope import envelope
from app.services import overview as overview_service

router = APIRouter(prefix="/api/v1", tags=["me"])


@router.get("/me/overview")
def get_overview(request: Request, db: DbSession, student: CurrentStudent) -> dict:
    data = overview_service.build_overview(db, student)
    return envelope(request, data)


@router.get("/me/mastery-history")
def get_mastery_history(
    request: Request, db: DbSession, student: CurrentStudent, concept_id: str
) -> dict:
    data = overview_service.mastery_history(db, student, concept_id)
    return envelope(request, data)
