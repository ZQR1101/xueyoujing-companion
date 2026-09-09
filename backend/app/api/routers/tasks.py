"""任务端点（合同 v1.2 R7）：讲解确认。"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.deps import CurrentStudent, DbSession
from app.api.dto import StrictModel
from app.api.envelope import envelope
from app.api.idempotency import run_idempotent
from app.infrastructure.models import Task
from app.services import tutoring as tutoring_service

router = APIRouter(prefix="/api/v1", tags=["tasks"])


class AcknowledgeTask(StrictModel):
    expected_version: int = 1


@router.post("/tasks/{task_id}/acknowledge")
def acknowledge_task(
    request: Request,
    db: DbSession,
    student: CurrentStudent,
    task_id: str,
    payload: AcknowledgeTask,
) -> dict:
    def execute(session) -> tuple[dict, int, None]:  # noqa: ANN001
        task = session.get(Task, task_id)
        if task is None or task.student_id != student.id:
            from app.domain.errors import ResourceNotFound

            raise ResourceNotFound("任务不存在或不属于当前学生")
        dto = tutoring_service.acknowledge_lesson(
            session,
            student=student,
            task=task,
            expected_version=payload.expected_version,
            correlation_id=getattr(request.state, "trace_id", None),
        )
        return {"task": dto}, task.version, None

    return run_idempotent(
        db,
        student_id=student.id,
        request=request,
        payload=payload.model_dump(),
        execute=execute,
    )
