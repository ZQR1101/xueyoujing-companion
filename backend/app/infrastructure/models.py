"""持久化模型：规格书 §6 数据契约全部实体 + §6/§11 补充表。

- 可变实体带整数 version（乐观并发）。
- 时间一律 UTC（naive datetime，写入前由 utcnow() 统一）。
- 列表字段以 JSON 存储，写入时整体替换（不做原地可变修改）。
- 枚举值以 String 存储并在应用层用 domain.enums 约束。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _uuid() -> str:
    import uuid

    return str(uuid.uuid4())


class Student(Base):
    __tablename__ = "students"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    display_name: Mapped[str] = mapped_column(String(80))
    timezone: Mapped[str] = mapped_column(String(40), default="Asia/Shanghai")
    daily_minutes: Mapped[int] = mapped_column(Integer, default=30)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        CheckConstraint("daily_minutes BETWEEN 5 AND 120", name="ck_student_daily_minutes"),
    )


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id"), index=True)
    course_id: Mapped[str] = mapped_column(String(40), index=True)
    target_concept_ids: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="active")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Concept(Base):
    __tablename__ = "concepts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    course_id: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(120))
    prerequisite_ids: Mapped[list] = mapped_column(JSON, default=list)
    resource_ids: Mapped[list] = mapped_column(JSON, default=list)


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    course_id: Mapped[str] = mapped_column(String(40), index=True)
    primary_concept_id: Mapped[str] = mapped_column(String(40), index=True)
    family_id: Mapped[str] = mapped_column(String(60), index=True)
    type: Mapped[str] = mapped_column(String(20))
    purpose: Mapped[str] = mapped_column(String(20))
    prompt: Mapped[str] = mapped_column(Text)
    public_options: Mapped[list] = mapped_column(JSON, default=list)
    difficulty: Mapped[int] = mapped_column(Integer, default=1)
    private_answer: Mapped[dict] = mapped_column(JSON)
    private_hints: Mapped[list] = mapped_column(JSON, default=list)
    private_solution: Mapped[str | None] = mapped_column(Text, nullable=True)
    numeric_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class LearningSession(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id"), index=True)
    goal_id: Mapped[str] = mapped_column(ForeignKey("goals.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="ready")
    current_task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Assessment(Base):
    __tablename__ = "assessments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id"), index=True)
    goal_id: Mapped[str] = mapped_column(ForeignKey("goals.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="in_progress")
    question_ids: Mapped[list] = mapped_column(JSON, default=list)
    coverage: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id"), index=True)
    goal_id: Mapped[str] = mapped_column(ForeignKey("goals.id"), index=True)
    plan_version: Mapped[int] = mapped_column(Integer, default=1)
    concept_id: Mapped[str] = mapped_column(String(40), index=True)
    type: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=5)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Exercise(Base):
    __tablename__ = "exercises"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id"), index=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    assessment_id: Mapped[str | None] = mapped_column(
        ForeignKey("assessments.id"), nullable=True, index=True
    )
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id"))
    hint_level: Mapped[int] = mapped_column(Integer, default=0)
    solution_seen: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(10), default="open")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        CheckConstraint(
            "(task_id IS NULL) <> (assessment_id IS NULL)",
            name="ck_exercise_single_owner",
        ),
    )


class Attempt(Base):
    __tablename__ = "attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    exercise_id: Mapped[str] = mapped_column(ForeignKey("exercises.id"), index=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id"), index=True)
    answer: Mapped[str] = mapped_column(Text)
    grade: Mapped[str] = mapped_column(String(10))
    hint_level_at_submission: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Evidence(Base):
    __tablename__ = "evidences"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id"), index=True)
    concept_id: Mapped[str] = mapped_column(String(40), index=True)
    attempt_id: Mapped[str] = mapped_column(ForeignKey("attempts.id"), index=True)
    family_id: Mapped[str] = mapped_column(String(60))
    score: Mapped[int] = mapped_column(Integer)
    eligible: Mapped[bool] = mapped_column(Boolean, default=True)
    exclusion_reason: Mapped[str | None] = mapped_column(String(60), nullable=True)
    event_id: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        Index(
            "ux_evidence_student_family_eligible",
            "student_id",
            "family_id",
            unique=True,
            sqlite_where=text("eligible = 1"),
        ),
        CheckConstraint("score IN (0, 1)", name="ck_evidence_score"),
    )


class MasteryState(Base):
    __tablename__ = "mastery_states"

    student_id: Mapped[str] = mapped_column(
        ForeignKey("students.id"), primary_key=True
    )
    concept_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    evidence_strength: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="unassessed")
    recent_evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    review_due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id"), index=True)
    goal_id: Mapped[str] = mapped_column(ForeignKey("goals.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    ordered_concept_ids: Mapped[list] = mapped_column(JSON, default=list)
    # 生成时的节点状态快照：顺序或节点状态真正变化才升版（§9.3）
    node_status_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    active_task_ids: Mapped[list] = mapped_column(JSON, default=list)
    reason_code: Mapped[str] = mapped_column(String(40))
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    policy_version: Mapped[str] = mapped_column(String(20), default="v0-seed")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id"), index=True)
    session_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(40))
    reason_code: Mapped[str] = mapped_column(String(40))
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    input_state_version: Mapped[int] = mapped_column(Integer, default=0)
    planner_source: Mapped[str] = mapped_column(String(20), default="rule_fallback")
    model_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    fallback_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id"), index=True)
    session_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    type: Mapped[str] = mapped_column(String(30), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    schema_version: Mapped[str] = mapped_column(String(10), default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    correlation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class MemoryFact(Base):
    __tablename__ = "memory_facts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id"), index=True)
    course_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    concept_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    type: Mapped[str] = mapped_column(String(30))
    content: Mapped[str] = mapped_column(Text)
    evidence_event_ids: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="active")
    version: Mapped[int] = mapped_column(Integer, default=1)
    supersedes_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    source_session_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class LearningReflection(Base):
    """T14-B 可恢复的学习小结；不承载掌握度或计划状态。"""
    __tablename__ = "learning_reflections"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id"), index=True)
    course_id: Mapped[str] = mapped_column(String(40), index=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    planner_source: Mapped[str] = mapped_column(String(30), default="reflection_rule_fallback")
    fallback_reason: Mapped[str | None] = mapped_column(String(160), nullable=True)
    learned: Mapped[list] = mapped_column(JSON, default=list)
    still_uncertain: Mapped[list] = mapped_column(JSON, default=list)
    evidence_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    next_recommendation: Mapped[dict] = mapped_column(JSON, default=dict)
    learning_characteristics: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # 作用域分区键（真实学生 id；身份创建端点使用 "*"），不是外键引用
    student_id: Mapped[str] = mapped_column(String(36), index=True)
    method: Mapped[str] = mapped_column(String(6))
    path: Mapped[str] = mapped_column(String(200))
    key: Mapped[str] = mapped_column(String(120))
    request_hash: Mapped[str] = mapped_column(String(64))
    response_status: Mapped[int] = mapped_column(Integer)
    response_body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("student_id", "method", "path", "key", name="ux_idempotency"),
    )


class MasterySnapshot(Base):
    """§7.3 before/after 快照：回放相同事件应得到相同结果。"""

    __tablename__ = "mastery_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id"), index=True)
    concept_id: Mapped[str] = mapped_column(String(40), index=True)
    evidence_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    attempt_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    formula_version: Mapped[str] = mapped_column(String(10))
    before: Mapped[dict] = mapped_column(JSON)
    after: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class LLMUsage(Base):
    """LLM 调用用量记录（T07 网关写入）。"""

    __tablename__ = "llm_usage"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    student_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    purpose: Mapped[str] = mapped_column(String(40))
    model_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DiagnosisReport(Base):
    """T10-B AI 学情诊断记录（与确定性评分分开保存；只增不改）。

    status: ok / insufficient_evidence
    planner_source: llm / rule_fallback（模型失败、虚构 ID、证据不足等一律规则回退并标记）
    """

    __tablename__ = "diagnosis_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id"), index=True)
    goal_id: Mapped[str] = mapped_column(ForeignKey("goals.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="ok")
    planner_source: Mapped[str] = mapped_column(String(20), default="rule_fallback")
    model_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    fallback_reason: Mapped[str | None] = mapped_column(String(160), nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    observations: Mapped[list] = mapped_column(JSON, default=list)
    hypotheses: Mapped[list] = mapped_column(JSON, default=list)
    recommended_probe: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    # 生成时的学习状态快照（证据计数/掌握签名），用于决策重放与排查
    input_state: Mapped[dict] = mapped_column(JSON, default=dict)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PathDecision(Base):
    """T11-B LLM 路径决策轨迹（候选集合、最终选择、理由、证据、耗时与回退原因）。"""

    __tablename__ = "path_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id"), index=True)
    goal_id: Mapped[str] = mapped_column(ForeignKey("goals.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="unchanged")  # adjusted / unchanged / no_legal_action
    candidate_actions: Mapped[list] = mapped_column(JSON, default=list)
    selected_action: Mapped[dict] = mapped_column(JSON, default=dict)
    reason: Mapped[str] = mapped_column(Text, default="")
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    policy_version: Mapped[str] = mapped_column(String(20), default="v1-rules")
    planner_source: Mapped[str] = mapped_column(String(20), default="rule_fallback")
    model_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    fallback_reason: Mapped[str | None] = mapped_column(String(160), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    plan_version_before: Mapped[int] = mapped_column(Integer, default=0)
    plan_version_after: Mapped[int] = mapped_column(Integer, default=0)
    changed: Mapped[bool] = mapped_column(Boolean, default=False)
    # 相同输入、规则版本和候选集合的重放依据（规范化状态哈希）
    input_state_hash: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RagTrace(Base):
    """T13-B 检索轨迹：原始/改写查询、过滤、候选、重排、最终来源、生成与回退标记。"""

    __tablename__ = "rag_traces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    student_id: Mapped[str] = mapped_column(String(36), index=True)
    raw_query: Mapped[str] = mapped_column(Text)
    rewritten_query: Mapped[str] = mapped_column(Text)
    filters: Mapped[dict] = mapped_column(JSON, default=dict)
    index_version: Mapped[str] = mapped_column(String(32), default="")
    candidates: Mapped[list] = mapped_column(JSON, default=list)
    reranked: Mapped[list] = mapped_column(JSON, default=list)
    final_sources: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default="ok")
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    safe_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    planner_source: Mapped[str] = mapped_column(String(20), default="rule_fallback")
    model_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    fallback_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    flags: Mapped[dict] = mapped_column(JSON, default=dict)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    concept_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    exercise_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    content_type: Mapped[str] = mapped_column(String(20), default="explanation")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
