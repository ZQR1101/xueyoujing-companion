"""T13-B Agentic RAG 教学链路（固定管线，规划书 T13-B）。

接收学生问题/错误类型 → 查询改写 → 混合检索（关键词+向量）→ 去重与重排
→ 课程/知识点/内容类型过滤 → 可靠性阈值判断 → 选择资源 → 生成带引用内容
→ 保存检索 trace。

硬约束：
- 检索分数只表示资料相关性，绝不进入掌握度/评分/路径计算（本服务不写任何业务状态表）；
- 生成内容只能引用实际返回的 source_id；引用校验失败禁止展示生成内容；
- hint 类型做答案泄露检查（T12-B 规则延续）；
- 低于可靠性阈值 → no_reliable_source，不编造内容；
- 向量失败→关键词；均失败→课程包固定资源；重排失败→初始顺序+rag_fallback；
  模型超时/Schema 不符 → 结构化错误，不阻塞答题与评分。
"""

from __future__ import annotations

import json
import re
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.errors import ResourceNotFound
from app.infrastructure.config import get_settings
from app.infrastructure.llm.gateway import LLMGateway, build_gateway
from app.infrastructure.models import Exercise, Question, RagTrace, Student
from app.infrastructure.rag_index import RagIndex, RagSegment, get_rag_index

RELIABILITY_THRESHOLD = 0.30
ERROR_KEYWORDS = {
    "sign": "符号 正负 括号",
    "sign_confusion": "符号 括号 正负",
    "substitution": "代入 求值",
    "vertex": "顶点 顶点式",
    "shift": "平移 移动",
    "axis": "对称轴",
    "opening": "开口 方向",
    "coeff": "系数 a 开口",
    "application": "应用 综合",
}
SYSTEM_PROMPT = (
    "你是课程资料讲解 Agent。只输出 JSON：{content: 面向初中生的讲解正文}。"
    "只基于给定 sources 摘要组织内容，用 [1] [2] 标注引用的来源序号；"
    "绝不给出题目标准答案，绝不引用未提供的来源。"
    "直接输出 JSON，不要展示思考过程，正文不超过 200 字。"
)
_SAFE_NO_SOURCE = "暂时没有找到可靠的课程资料，建议先继续当前练习，稍后再试。"


def rewrite_query(query: str, concept_title: str | None, error_code: str | None) -> str:
    """规则改写：补充知识点与错误类型检索词；原始 query 原样保留。"""
    parts = [query.strip()]
    if concept_title:
        parts.append(concept_title)
    keywords = ERROR_KEYWORDS.get((error_code or "").lower(), "")
    if keywords:
        parts.append(keywords)
    return " ".join(p for p in parts if p)


def _seg_view(segment: RagSegment, score: float, rank: int) -> dict:
    return {
        "source_id": segment.source_id,
        "title": segment.title,
        "concept_id": segment.concept_id,
        "content_type": segment.content_type,
        "heading": segment.heading,
        "excerpt": segment.text[:160],
        "retrieval_score": score,
        "rank": rank,
    }


def _hybrid_retrieve(index: RagIndex, rewritten: str) -> tuple[list[tuple[RagSegment, float]], dict]:
    flags: dict = {}
    try:
        kw = index.keyword_search(rewritten, top_k=8)
    except Exception:  # noqa: BLE001（任一检索臂失败都降级，不让 RAG 阻塞学习）
        kw = []
        flags["keyword_fallback"] = True
    try:
        vec = index.vector_search(rewritten, top_k=8)
    except Exception:  # noqa: BLE001
        vec = []
        flags["vector_fallback"] = True
    if not kw and not vec:
        return [], flags
    # 单臂可用时权重归一化，避免故障降级把所有得分折半、全部掉到可靠性阈值之下
    kw_weight = 0.5 if vec else 1.0
    vec_weight = 0.5 if kw else 1.0
    by_id = {s.source_id: s for s, _ in list(kw) + list(vec)}
    merged: dict[str, float] = {}
    for seg, score in kw:
        merged[seg.source_id] = merged.get(seg.source_id, 0.0) + kw_weight * score
    for seg, score in vec:
        merged[seg.source_id] = merged.get(seg.source_id, 0.0) + vec_weight * score
    results = sorted(
        ((by_id[sid], round(score, 4)) for sid, score in merged.items()),
        key=lambda item: (-item[1], item[0].source_id),
    )
    return results, flags


def _rerank(
    candidates: list[tuple[RagSegment, float]],
    *,
    concept_id: str | None,
    content_type: str,
    rewritten: str,
) -> tuple[list[tuple[RagSegment, float]], bool]:
    """规则重排：概念匹配与内容类型加权；异常时沿用初始顺序（调用方捕获）。"""
    def bonus(item: tuple[RagSegment, float]) -> float:
        seg, score = item
        b = 0.0
        if concept_id and seg.concept_id == concept_id:
            b += 0.15
        if seg.content_type == content_type:
            b += 0.10
        return round(score + b, 4)

    return sorted(((s, bonus((s, sc))) for s, sc in candidates), key=lambda i: (-i[1], i[0].source_id)), False


def _private_answer(db: Session, exercise: Exercise) -> str | None:
    row = db.execute(
        select(Question.private_answer).where(Question.id == exercise.question_id)
    ).scalar()
    return json.dumps(row, ensure_ascii=False) if row is not None else None


def _validate_generation(parsed: object, sources: list[dict], private_answer: str | None) -> tuple[str | None, str | None]:
    if not isinstance(parsed, dict):
        return None, "generation_not_object"
    content = parsed.get("content")
    if not isinstance(content, str) or not content.strip():
        return None, "content_missing"
    content = content.strip()
    refs = {int(m) for m in re.findall(r"\[(\d+)\]", content)}
    if any(r < 1 or r > len(sources) for r in refs):
        return None, "citation_out_of_range"
    if private_answer:
        answer_texts = re.findall(r'"value"\s*:\s*"([^"]+)"', private_answer)
        for answer in answer_texts:
            if answer and answer in content:
                return None, "answer_leak"
    return content, None


def _rule_content(sources: list[dict]) -> str:
    parts = []
    for s in sources[:3]:
        parts.append(f"[{s['rank']}] 《{s['title']}·{s['heading']}》：{s['excerpt']}")
    return "课程资料要点：\n" + "\n".join(parts) if parts else _SAFE_NO_SOURCE


def query_rag(
    db: Session,
    *,
    student: Student,
    query: str,
    content_type: str = "explanation",
    concept_id: str | None = None,
    exercise_id: str | None = None,
    error_code: str | None = None,
    allowed_concept_ids: list[str] | None = None,
    gateway: LLMGateway | None = None,
    index: RagIndex | None = None,
    correlation_id: str | None = None,
) -> tuple[dict, RagTrace]:
    started = time.monotonic()
    idx = index or get_rag_index()
    flags: dict = {}
    concept_title = None
    if concept_id:
        for seg in idx.segments:
            if seg.concept_id == concept_id:
                concept_title = seg.title
                break

    # 1) 查询改写（原始 query 保留）
    rewritten = rewrite_query(query, concept_title, error_code)

    # 2) 混合检索（向量失败→关键词；检索服务故障（两臂均异常）→课程包固定资源）
    candidates, rflags = _hybrid_retrieve(idx, rewritten)
    flags.update(rflags)
    retrieval_broken = bool(flags.get("keyword_fallback") or flags.get("vector_fallback"))
    if not candidates and retrieval_broken:
        candidates = idx.fixed_fallback(concept_id)
        flags["retrieve_fallback"] = True

    # 3) 去重与重排
    deduped: dict[str, tuple[RagSegment, float]] = {}
    for seg, score in candidates:
        deduped.setdefault(seg.source_id, (seg, score))
    candidate_list = list(deduped.values())
    try:
        reranked, _ = _rerank(candidate_list, concept_id=concept_id, content_type=content_type, rewritten=rewritten)
    except Exception:  # noqa: BLE001（重排失败→初始顺序 + rag_fallback）
        reranked = candidate_list
        flags["rag_fallback"] = True

    # 4) 过滤：课程、知识点（当前任务范围）、内容类型（严格为空时放宽并标记）
    allowed = set(allowed_concept_ids) if allowed_concept_ids else None
    private_answer = None
    if exercise_id:
        exercise = db.get(Exercise, exercise_id)
        if exercise is None or exercise.student_id != student.id:
            raise ResourceNotFound("题目不存在或不属于当前学生")
        if concept_id is None:
            question = db.get(Question, exercise.question_id)
            concept_id = question.primary_concept_id
        if content_type == "hint":
            private_answer = _private_answer(db, exercise)
    question_prompt = None
    if exercise_id:
        exercise = db.get(Exercise, exercise_id)
        if exercise is not None:
            question_prompt = db.get(Question, exercise.question_id).prompt

    def _pass(seg: RagSegment) -> bool:
        if seg.course_id != idx.course_id:
            return False
        if allowed is not None and seg.concept_id not in allowed:
            return False
        if concept_id and seg.concept_id != concept_id:
            return False
        return True

    def _answer_safe(text: str) -> bool:
        if not private_answer:
            return True
        answer_texts = re.findall(r'"value"\s*:\s*"([^"]+)"', private_answer)
        return not any(a and a in text for a in answer_texts)

    strict = [(s, sc) for s, sc in reranked if _pass(s) and s.content_type == content_type and _answer_safe(s.text)]
    if strict:
        filtered = strict
    else:
        # 严格内容类型为空时放宽类型（保持课程/知识点/答案安全过滤），并留痕
        filtered = [(s, sc) for s, sc in reranked if _pass(s) and _answer_safe(s.text)]
        if filtered:
            flags["content_type_relaxed"] = True

    # 5) 可靠性阈值
    final_sources = [_seg_view(seg, score, i + 1) for i, (seg, score) in enumerate(filtered[:4])]
    if not final_sources or final_sources[0]["retrieval_score"] < RELIABILITY_THRESHOLD:
        status = "no_reliable_source"
        content = None
        safe_message = _SAFE_NO_SOURCE
        planner_source, model_id, fallback_reason = "rule_fallback", None, "below_reliability_threshold"
    else:
        status = "ok"
        safe_message = None
        # 6) 生成带引用内容
        gw = gateway or build_gateway()
        gen_payload = {
            "task": "基于 sources 摘要写一段面向初中生的讲解正文，用 [n] 标注引用的来源序号。",
            "expected_content_type": content_type,
            "question_excerpt": question_prompt,
            "sources": final_sources,
            "legal_actions": [],
        }
        # All DB reads are complete.  Release SQLite's writer lock before the
        # network call; trace/usage persistence happens afterwards.
        if db.in_transaction():
            db.commit()
        generation_timeout = min(get_settings().llm_timeout_seconds, 20.0)
        outcome = gw.decide(payload=gen_payload, system=SYSTEM_PROMPT, timeout=generation_timeout)
        _record_usage(db, student_id=student.id, outcome=outcome)
        validation_error: str | None = outcome.error
        generated: str | None = None
        model_id = None
        if outcome.parsed is not None:
            generated, validation_error = _validate_generation(outcome.parsed, final_sources, private_answer)
            if generated is None:
                outcome2 = gw.decide(
                    payload=gen_payload, validation_error=validation_error, system=SYSTEM_PROMPT, timeout=generation_timeout
                )
                _record_usage(db, student_id=student.id, outcome=outcome2)
                if outcome2.parsed is not None:
                    generated, validation_error = _validate_generation(outcome2.parsed, final_sources, private_answer)
                    if generated is not None:
                        model_id = outcome2.usage.get("model_id")
                else:
                    validation_error = outcome2.error
            else:
                model_id = outcome.usage.get("model_id")

        if generated is not None and model_id is not None:
            content = generated
            planner_source = "llm"
            fallback_reason = None
        else:
            # 引用校验失败/模型超时：禁止展示生成内容，回退为可溯源的资料摘要（规则生成）
            content = _rule_content(final_sources)
            planner_source = "rule_fallback"
            fallback_reason = validation_error or outcome.error or "model_unavailable"
            status = "rag_fallback"

    duration_ms = int((time.monotonic() - started) * 1000)
    trace = RagTrace(
        student_id=student.id,
        raw_query=query,
        rewritten_query=rewritten,
        filters={
            "course_id": idx.course_id,
            "concept_id": concept_id,
            "content_type": content_type,
            "exercise_id": exercise_id,
            "allowed_concept_ids": allowed_concept_ids,
        },
        index_version=idx.index_version,
        candidates=[_seg_view(s, sc, i + 1) for i, (s, sc) in enumerate(candidate_list)],
        reranked=[_seg_view(s, sc, i + 1) for i, (s, sc) in enumerate(reranked)],
        final_sources=final_sources,
        status=status,
        content=content,
        safe_message=safe_message,
        planner_source=planner_source,
        model_id=model_id,
        fallback_reason=fallback_reason,
        flags=flags,
        duration_ms=duration_ms,
        concept_id=concept_id,
        exercise_id=exercise_id,
        content_type=content_type,
    )
    db.add(trace)
    db.flush()

    data = {
        "trace_id": trace.id,
        "status": status,
        "content": content,
        "safe_message": safe_message,
        "sources": final_sources,
        "rewritten_query": rewritten,
        "raw_query": query,
        "planner_source": planner_source,
        "model_id": model_id,
        "fallback_reason": fallback_reason,
        "flags": flags,
        "index_version": idx.index_version,
        "duration_ms": duration_ms,
    }
    return data, trace


def get_trace(db: Session, student_id: str, trace_id: str) -> RagTrace:
    trace = db.get(RagTrace, trace_id)
    if trace is None or trace.student_id != student_id:
        raise ResourceNotFound("检索记录不存在或不属于当前学生")
    return trace


def _record_usage(db: Session, *, student_id: str, outcome) -> None:
    from app.infrastructure.models import LLMUsage

    for attempt in outcome.attempts:
        db.add(
            LLMUsage(
                student_id=student_id,
                purpose="rag_generation",
                model_id=outcome.usage.get("model_id"),
                prompt_tokens=attempt.get("prompt_tokens", 0),
                completion_tokens=attempt.get("completion_tokens", 0),
                ok=attempt.get("error") is None,
            )
        )
    db.flush()
