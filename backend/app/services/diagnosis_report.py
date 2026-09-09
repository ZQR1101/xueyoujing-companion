"""T10-B AI 学情诊断（结构化 Schema + 规则回退，规划书 T10-B）。

- 结构化诊断结果至少包含 observations / hypotheses / recommended_probe / evidence_ids；
- 所有 concept_id / evidence_id 必须经过当前学生归属与课程存在性校验；
- 模型失败、超时、非法 JSON、虚构 ID 或证据不足时返回可解释的规则回退（rule_fallback），
  不阻塞学生继续学习；
- AI 诊断与确定性评分分开保存：本服务只写 diagnosis_reports / llm_usage，
  不触碰 MasteryState / Evidence。
"""

from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.curriculum import get_course_data
from app.infrastructure.llm.gateway import LLMGateway, build_gateway
from app.infrastructure.models import (
    DiagnosisReport,
    Evidence,
    Goal,
    LLMUsage,
    MasteryState,
    Student,
)
from app.infrastructure.repositories import learning as learning_repo
from app.services import planner as planner_service

MIN_EVIDENCE_FOR_AI = 2
POLICY_VERSION = "t10b-v1"
SYSTEM_PROMPT = (
    "你是初中数学学情诊断 Agent。只输出 JSON："
    "{summary, observations:[{concept_id,title,detail}], hypotheses:[{concept_id,title,detail}], "
    "recommended_probe:{concept_id,summary}, evidence_ids:[...]}。"
    "只使用给定 state 中的概念与证据 ID，不编造。"
)


# ---------------------------------------------------------------------------
# 状态读取（只读）
# ---------------------------------------------------------------------------

def collect_state(db: Session, *, student: Student, goal: Goal) -> dict:
    """读取学习状态：掌握签名 + 近期证据摘要（不含答案/提示等私有内容）。"""
    course = get_course_data()
    targets = [c for c in course.topo_order if c in set(goal.target_concept_ids)]
    states = learning_repo.mastery_states_for_concepts(db, student.id, targets)

    concepts = []
    for cid in targets:
        state: MasteryState | None = states.get(cid)
        title = course.concept(cid)["title"] if course.concept(cid) else cid
        concepts.append(
            {
                "concept_id": cid,
                "title": title,
                "status": state.status if state else "unassessed",
                "estimate": state.estimate if state else None,
                "evidence_count": state.evidence_count if state else 0,
                "distinct_error_exercises": planner_service.distinct_error_exercises(
                    db, student.id, cid
                ),
            }
        )

    evidences = learning_repo.latest_evidences(db, student.id, limit=12)
    target_set = set(targets)
    evidence_view = [
        {
            "evidence_id": e.id,
            "concept_id": e.concept_id,
            "family_id": e.family_id,
            "score": e.score,
            "eligible": e.eligible,
            "exclusion_reason": e.exclusion_reason,
        }
        for e in evidences
        if e.concept_id in target_set
    ]

    eligible_count = sum(1 for e in evidence_view if e["eligible"])
    assessed = [c for c in concepts if c["evidence_count"]]
    return {
        "policy_version": POLICY_VERSION,
        "course_id": goal.course_id,
        "concepts": concepts,
        "evidences": evidence_view,
        "evidence_total": len(evidence_view),
        "eligible_total": eligible_count,
        "assessed_total": len(assessed),
        "coverage": {
            "assessed_count": len(assessed),
            "total_count": len(targets),
        },
    }


# ---------------------------------------------------------------------------
# 规则回退（可解释，不依赖模型）
# ---------------------------------------------------------------------------

def _rule_report(state: dict) -> dict:
    """规则推导诊断：无模型时也能给出稳定、可解释的结果。"""
    concepts = state["concepts"]
    if not any(c["evidence_count"] for c in concepts):
        return {
            "status": "insufficient_evidence",
            "summary": "还没有足够的作答证据，先完成几道诊断题再生成学情分析。",
            "observations": [],
            "hypotheses": [],
            "recommended_probe": {
                "concept_id": None,
                "summary": "先完成本轮诊断题，建立初始学习基准。",
                "reason": "no_evidence",
            },
            "evidence_ids": [],
        }

    def sort_key(c: dict) -> tuple:
        estimate = c["estimate"] if c["estimate"] is not None else 1.0
        status_rank = {"needs_support": 0, "developing": 1}.get(c["status"], 2)
        return (status_rank, estimate, -c["distinct_error_exercises"], c["concept_id"])

    weak = sorted(
        [c for c in concepts if c["evidence_count"] and c["status"] != "mastered"],
        key=sort_key,
    )
    unassessed = [c for c in concepts if not c["evidence_count"]]
    mastered = [c for c in concepts if c["status"] == "mastered"]

    observations: list[dict] = []
    hypotheses: list[dict] = []
    evidence_ids = [e["evidence_id"] for e in state["evidences"] if e["eligible"]][:8]

    if weak:
        focus = weak[0]
        err = focus["distinct_error_exercises"]
        observations.append(
            {
                "concept_id": focus["concept_id"],
                "title": f"「{focus['title']}」掌握仍在发展中",
                "detail": (
                    f"当前状态 {focus['status']}"
                    + (f"，估计 {focus['estimate']:.0%}。" if focus["estimate"] is not None else "。")
                    + (f"已有 {err} 道不同题出现错误。" if err else "暂无重复错误。")
                ),
            }
        )
        hypotheses.append(
            {
                "concept_id": focus["concept_id"],
                "title": f"「{focus['title']}」需要进一步确认",
                "detail": "建议通过一道新的独立题验证是偶发失误还是稳定性问题。",
            }
        )
    for c in mastered[:1]:
        observations.append(
            {
                "concept_id": c["concept_id"],
                "title": f"「{c['title']}」已达到掌握门槛",
                "detail": "近期独立作答表现稳定，可作为后续知识点的先修基础。",
            }
        )
    if unassessed:
        hypotheses.append(
            {
                "concept_id": unassessed[0]["concept_id"],
                "title": f"「{unassessed[0]['title']}」尚未评估",
                "detail": "将在后续学习中安排补测，逐步建立完整认知图谱。",
            }
        )

    probe_target = weak[0] if weak else (unassessed[0] if unassessed else None)
    if probe_target is not None:
        probe = {
            "concept_id": probe_target["concept_id"],
            "summary": f"先做一道「{probe_target['title']}」基础补测题，确认是否需要巩固。",
            "reason": "rule_weakest_concept" if weak else "rule_unassessed",
        }
    else:
        probe = {
            "concept_id": None,
            "summary": "当前目标知识点均已达掌握门槛，按计划继续推进即可。",
            "reason": "rule_all_mastered",
        }

    return {
        "status": "ok",
        "summary": (
            f"已经掌握 {len(mastered)} 个知识点，"
            + (f"「{weak[0]['title']}」还需要进一步确认。" if weak else "其余知识点按计划继续。")
        ),
        "observations": observations,
        "hypotheses": hypotheses,
        "recommended_probe": probe,
        "evidence_ids": evidence_ids,
    }


# ---------------------------------------------------------------------------
# LLM 结构化输出校验
# ---------------------------------------------------------------------------

def _validate_parsed(db: Session, *, student_id: str, parsed: object, state: dict) -> tuple[dict | None, str | None]:
    """Schema + 归属校验。返回 (规范化结果, 错误码)。规则权威，模型只能在给定范围内引用。"""
    import json as _json

    if not isinstance(parsed, dict):
        return None, "diagnosis_not_object"
    try:
        observations = parsed.get("observations")
        hypotheses = parsed.get("hypotheses")
        probe = parsed.get("recommended_probe")
        summary = parsed.get("summary")
    except AttributeError:
        return None, "diagnosis_shape_invalid"

    if not isinstance(summary, str) or not summary.strip():
        return None, "summary_missing"
    if not isinstance(observations, list) or not isinstance(hypotheses, list):
        return None, "lists_invalid"
    if not isinstance(probe, dict):
        return None, "probe_invalid"

    valid_concepts = {c["concept_id"] for c in state["concepts"]}
    known_evidence = {e["evidence_id"] for e in state["evidences"]}

    def clean_items(items: object, kind: str) -> tuple[list[dict], str | None]:
        cleaned: list[dict] = []
        if not isinstance(items, list):
            return [], f"{kind}_not_list"
        for item in items[:4]:
            if not isinstance(item, dict):
                return [], f"{kind}_item_invalid"
            title = item.get("title")
            detail = item.get("detail")
            if not isinstance(title, str) or not title.strip():
                return [], f"{kind}_title_missing"
            cid = item.get("concept_id")
            if cid is not None and cid not in valid_concepts:
                return [], f"fabricated_concept_id:{cid}"
            cleaned.append(
                {
                    "concept_id": cid,
                    "title": title.strip()[:60],
                    "detail": (detail or "").strip()[:200] if isinstance(detail, str) else "",
                }
            )
        return cleaned, None

    observations, err = clean_items(observations, "observations")
    if err:
        return None, err
    hypotheses, err = clean_items(hypotheses, "hypotheses")
    if err:
        return None, err

    if not observations and not hypotheses:
        return None, "empty_diagnosis"

    probe_concept = probe.get("concept_id")
    if probe_concept is not None and probe_concept not in valid_concepts:
        return None, f"fabricated_concept_id:{probe_concept}"
    probe_summary = probe.get("summary")
    if not isinstance(probe_summary, str) or not probe_summary.strip():
        return None, "probe_summary_missing"

    evidence_ids = parsed.get("evidence_ids") or []
    if not isinstance(evidence_ids, list):
        return None, "evidence_ids_not_list"
    for eid in evidence_ids:
        if eid not in known_evidence:
            return None, f"fabricated_evidence_id:{eid}"

    return (
        {
            "status": "ok",
            "summary": summary.strip()[:120],
            "observations": observations,
            "hypotheses": hypotheses,
            "recommended_probe": {
                "concept_id": probe_concept,
                "summary": probe_summary.strip()[:120],
                "reason": "llm_choice",
            },
            "evidence_ids": [e for e in evidence_ids][:8],
        },
        None,
    )


def _build_payload(state: dict) -> dict:
    return {
        "task": (
            "基于作答证据生成学情诊断。只输出 JSON：{summary, observations:[{concept_id,title,detail}], "
            "hypotheses:[{concept_id,title,detail}], recommended_probe:{concept_id,summary}, evidence_ids:[...]}"
        ),
        "constraints": [
            "concept_id 必须来自 concepts 列表，可为 null",
            "evidence_ids 必须来自 evidences 的 evidence_id",
            "不得编造未给出的知识点或证据；observations/hypotheses 不得同时为空",
        ],
        "state": state,
        "legal_actions": [],  # 占位：MockProvider 需要该键；诊断任务不提供教学行动
    }


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def generate_report(
    db: Session,
    *,
    student: Student,
    goal: Goal,
    gateway: LLMGateway | None = None,
    correlation_id: str | None = None,
) -> tuple[dict, DiagnosisReport]:
    """生成并持久化 AI 学情诊断。返回 (响应数据, 记录行)。"""
    started = time.monotonic()
    state = collect_state(db, student=student, goal=goal)

    parsed: dict | None = None
    planner_source = "rule_fallback"
    model_id: str | None = None
    fallback_reason: str | None = None
    status = "ok"

    if state["eligible_total"] < MIN_EVIDENCE_FOR_AI:
        # 证据不足：不调用模型，直接给可解释的规则结果
        fallback_reason = "insufficient_evidence"
        status = "insufficient_evidence"
        parsed = _rule_report(state)
        parsed["status"] = status
    else:
        gw = gateway or build_gateway()
        outcome = gw.decide(payload=_build_payload(state), system=SYSTEM_PROMPT)
        _record_usage(db, student_id=student.id, outcome=outcome)
        validation_error: str | None = outcome.error

        if outcome.parsed is not None:
            parsed, validation_error = _validate_parsed(
                db, student_id=student.id, parsed=outcome.parsed, state=state
            )
            if parsed is None:
                # 校验失败（含虚构 ID / 空诊断）→ 修复一次
                outcome2 = gw.decide(
                    payload=_build_payload(state), validation_error=validation_error, system=SYSTEM_PROMPT
                )
                _record_usage(db, student_id=student.id, outcome=outcome2)
                if outcome2.parsed is not None:
                    parsed, validation_error = _validate_parsed(
                        db, student_id=student.id, parsed=outcome2.parsed, state=state
                    )
                    if parsed is not None:
                        model_id = outcome2.usage.get("model_id")
                else:
                    validation_error = outcome2.error
            else:
                model_id = outcome.usage.get("model_id")

        if parsed is not None and model_id is not None:
            planner_source = "llm"
        else:
            fallback_reason = fallback_reason or validation_error or "model_unavailable"
            parsed = _rule_report(state)

    duration_ms = int((time.monotonic() - started) * 1000)
    report = DiagnosisReport(
        student_id=student.id,
        goal_id=goal.id,
        status=status if status != "ok" else parsed["status"],
        planner_source=planner_source,
        model_id=model_id,
        fallback_reason=fallback_reason,
        summary=parsed["summary"],
        observations=parsed["observations"],
        hypotheses=parsed["hypotheses"],
        recommended_probe=parsed["recommended_probe"],
        evidence_ids=parsed["evidence_ids"],
        input_state={
            "policy_version": POLICY_VERSION,
            "evidence_total": state["evidence_total"],
            "eligible_total": state["eligible_total"],
            "coverage": state["coverage"],
            "mastery_signature": {
                c["concept_id"]: c["status"] for c in state["concepts"]
            },
        },
        duration_ms=duration_ms,
    )
    db.add(report)
    db.flush()

    data = {
        "report_id": report.id,
        "status": report.status,
        "planner_source": planner_source,
        "model_id": model_id,
        "fallback_reason": fallback_reason,
        "summary": report.summary,
        "observations": report.observations,
        "hypotheses": report.hypotheses,
        "recommended_probe": report.recommended_probe,
        "evidence_ids": report.evidence_ids,
        "state": {
            "evidence_total": state["evidence_total"],
            "eligible_total": state["eligible_total"],
            "coverage": state["coverage"],
            "mastery": [
                {
                    "concept_id": c["concept_id"],
                    "title": c["title"],
                    "status": c["status"],
                    "estimate": c["estimate"],
                    "evidence_count": c["evidence_count"],
                }
                for c in state["concepts"]
            ],
        },
        "policy_version": POLICY_VERSION,
        "duration_ms": duration_ms,
    }
    return data, report


def latest_report(db: Session, student_id: str, goal_id: str) -> DiagnosisReport | None:
    return db.execute(
        select(DiagnosisReport)
        .where(DiagnosisReport.student_id == student_id, DiagnosisReport.goal_id == goal_id)
        .order_by(DiagnosisReport.created_at.desc())
    ).scalars().first()


def _record_usage(db: Session, *, student_id: str, outcome) -> None:
    for attempt in outcome.attempts:
        db.add(
            LLMUsage(
                student_id=student_id,
                purpose="diagnosis_report",
                model_id=outcome.usage.get("model_id"),
                prompt_tokens=attempt.get("prompt_tokens", 0),
                completion_tokens=attempt.get("completion_tokens", 0),
                ok=attempt.get("error") is None,
            )
        )
    db.flush()
