"""T13-B Agentic RAG 端点。

- POST /tutoring/rag：检索+带引用生成（幂等；学生视图返回简短讲解 + sources）；
- GET  /tutoring/rag/traces/{trace_id}：技术视图，完整检索 trace（归属校验）；
- GET  /tutoring/rag/sources/{source_id}：来源查询（跨课程资源不可见 → 404）。
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.deps import CurrentStudent, DbSession
from app.api.dto import RagQuery
from app.api.envelope import envelope
from app.api.idempotency import run_idempotent_after_external_work
from app.infrastructure.rag_index import get_rag_index
from app.services import tutoring_rag as rag_service

router = APIRouter(prefix="/api/v1", tags=["tutoring-rag"])


@router.post("/tutoring/rag")
def query_rag(
    request: Request, db: DbSession, student: CurrentStudent, payload: RagQuery
) -> dict:
    def execute(session) -> tuple[dict, int | None, None]:  # noqa: ANN001
        data, _trace = rag_service.query_rag(
            session,
            student=student,
            query=payload.query,
            content_type=payload.content_type,
            concept_id=payload.concept_id,
            exercise_id=payload.exercise_id,
            error_code=payload.error_code,
            allowed_concept_ids=payload.allowed_concept_ids,
            correlation_id=getattr(request.state, "trace_id", None),
        )
        return data, None, None

    return run_idempotent_after_external_work(
        db,
        student_id=student.id,
        request=request,
        payload=payload.model_dump(),
        execute=execute,
    )


@router.get("/tutoring/rag/traces/{trace_id}")
def get_rag_trace(
    request: Request, db: DbSession, student: CurrentStudent, trace_id: str
) -> dict:
    trace = rag_service.get_trace(db, student.id, trace_id)
    data = {
        "trace_id": trace.id,
        "raw_query": trace.raw_query,
        "rewritten_query": trace.rewritten_query,
        "filters": trace.filters,
        "index_version": trace.index_version,
        "candidates": trace.candidates,
        "reranked": trace.reranked,
        "final_sources": trace.final_sources,
        "status": trace.status,
        "content": trace.content,
        "safe_message": trace.safe_message,
        "planner_source": trace.planner_source,
        "model_id": trace.model_id,
        "fallback_reason": trace.fallback_reason,
        "flags": trace.flags,
        "duration_ms": trace.duration_ms,
        "created_at": trace.created_at.isoformat() + "Z",
    }
    return envelope(request, data)


@router.get("/tutoring/rag/sources/{source_id}")
def get_source(
    request: Request, db: DbSession, student: CurrentStudent, source_id: str
) -> dict:
    # db/student 用于鉴权一致性；索引按课程包构建，跨课程资源不可见
    segment = get_rag_index().by_source(source_id, course_id="quadratic")
    if segment is None:
        from app.domain.errors import ResourceNotFound

        raise ResourceNotFound("资料来源不存在")
    data = {
        "source_id": segment.source_id,
        "resource_id": segment.resource_id,
        "course_id": segment.course_id,
        "concept_id": segment.concept_id,
        "title": segment.title,
        "heading": segment.heading,
        "content_type": segment.content_type,
        "text": segment.text,
        "index_version": get_rag_index().index_version,
    }
    return envelope(request, data)
