"""演示身份端点（§12：POST /demo-identities）。

创建身份前尚无学生，幂等作用域使用固定匿名作用域 "*"。
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.deps import DbSession
from app.api.dto import CreateDemoIdentity
from app.api.idempotency import anonymous_scope, run_idempotent
from app.api.serializers import student_dto
from app.services import students as students_service

router = APIRouter(prefix="/api/v1", tags=["demo"])


@router.post("/demo-identities")
def create_demo_identity(
    request: Request, db: DbSession, payload: CreateDemoIdentity
) -> dict:
    def execute(session) -> tuple[dict, None, None]:  # noqa: ANN001
        student, token = students_service.create_demo_student(session, payload.display_name)
        return {"token": token, "student": student_dto(student)}, None, None

    return run_idempotent(
        db,
        student_id=anonymous_scope(None),
        request=request,
        payload=payload.model_dump(),
        execute=execute,
    )
