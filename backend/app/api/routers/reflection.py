"""T14-B 反思与可供 Planner 读取的有效记忆端点。"""
from fastapi import APIRouter, Request
from sqlalchemy import select
from app.api.deps import CurrentStudent, DbSession
from app.api.dto import GenerateReflection, MemoryCorrection
from app.api.envelope import envelope
from app.api.idempotency import run_idempotent
from app.domain.errors import ResourceNotFound
from app.infrastructure.models import Goal, LearningReflection
from app.services import reflection

router=APIRouter(prefix="/api/v1", tags=["reflection"])

@router.post("/sessions/{session_id}/reflection")
def create(request: Request, db: DbSession, student: CurrentStudent, session_id: str, payload: GenerateReflection):
    return run_idempotent(db, student_id=student.id, request=request, payload=payload.model_dump(), execute=lambda s: (reflection.generate(s,student_id=student.id,session_id=session_id,student_text=payload.text,force_llm_failure=payload.force_llm_failure),None,None))

@router.get("/sessions/{session_id}/reflection")
def get(request: Request, db: DbSession, student: CurrentStudent, session_id: str):
    r=db.execute(select(LearningReflection).where(LearningReflection.student_id==student.id,LearningReflection.session_id==session_id).order_by(LearningReflection.created_at.desc())).scalars().first()
    if not r: raise ResourceNotFound("尚未生成学习小结")
    return envelope(request, reflection.serialize(r))

@router.get("/courses/{course_id}/memories")
def memories(request: Request, db: DbSession, student: CurrentStudent, course_id: str, concept_id: str|None=None):
    if not db.execute(select(Goal).where(Goal.student_id==student.id,Goal.course_id==course_id)).scalars().first(): raise ResourceNotFound("课程不属于当前学生")
    return envelope(request, {"memories": reflection.active_memories(db, student.id, course_id, concept_id)})

@router.post("/memories/{memory_id}/correction")
def correct(request: Request, db: DbSession, student: CurrentStudent, memory_id: str, payload: MemoryCorrection):
    return run_idempotent(db,student_id=student.id,request=request,payload=payload.model_dump(),execute=lambda s:(reflection.mark(s,student.id,memory_id,payload.status),None,None))

@router.post("/memories/{memory_id}/restore")
def restore(request: Request, db: DbSession, student: CurrentStudent, memory_id: str):
    return run_idempotent(db,student_id=student.id,request=request,payload={},execute=lambda s:(reflection.mark(s,student.id,memory_id,"active"),None,None))

@router.get("/memories/{memory_id}/chain")
def chain(request: Request, db: DbSession, student: CurrentStudent, memory_id: str): return envelope(request, {"chain": reflection.chain(db, student.id, memory_id)})

@router.get("/sessions/{session_id}/reflection-overview")
def overview(request: Request, db: DbSession, student: CurrentStudent, session_id: str):
    r=db.execute(select(LearningReflection).where(LearningReflection.student_id==student.id,LearningReflection.session_id==session_id).order_by(LearningReflection.created_at.desc())).scalars().first()
    if not r: raise ResourceNotFound("尚未生成学习小结")
    return envelope(request, {**reflection.serialize(r), "active_memories": reflection.active_memories(db, student.id, r.course_id)})

@router.get("/sessions/{session_id}/next-recommendation")
def next_recommendation(request: Request, db: DbSession, student: CurrentStudent, session_id: str):
    r=db.execute(select(LearningReflection).where(LearningReflection.student_id==student.id,LearningReflection.session_id==session_id).order_by(LearningReflection.created_at.desc())).scalars().first()
    if not r: raise ResourceNotFound("尚未生成下一次学习建议")
    return envelope(request, r.next_recommendation)
