"""T07 Agent 与记忆测试（A12、A05 校验机制、决策轨迹、记忆引用）。"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from app.infrastructure.llm import gateway as gateway_module
from app.infrastructure.llm.gateway import LLMGateway, ScriptedProvider, TimeoutProvider
from app.infrastructure.models import LLMUsage, MemoryFact
from app.services import coordinator as coordinator_module
from app.domain.errors import IllegalState


def _key() -> str:
    return f"t07-{uuid4().hex}"


def _headers_of(client, name: str):
    r = client.post(
        "/api/v1/demo-identities", json={"display_name": name},
        headers={"Idempotency-Key": _key()},
    )
    return {"Authorization": f"Bearer {r.json()['data']['token']}"}


def _goal(client, headers, targets=None):
    r = client.post(
        "/api/v1/goals",
        json={"course_id": "quadratic", "target_concept_ids": targets or [], "daily_minutes": 30},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _sv(client, headers, session_id):
    return client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()["resource_version"]


def _setup_ready(client, name):
    headers = _headers_of(client, name)
    data = _goal(client, headers, targets=["C01"])
    session_id = data["session"]["id"]
    version = _sv(client, headers, session_id)
    r = client.post(
        f"/api/v1/sessions/{session_id}/diagnosis",
        json={"expected_version": version}, headers={**headers, "Idempotency-Key": _key()},
    )
    d = r.json()["data"]
    a = client.post(
        f"/api/v1/exercises/{d['exercise']['id']}/attempts",
        json={"answer": "B", "expected_version": d["exercise"]["version"]},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert a.status_code == 200
    cur = client.get(
        f"/api/v1/assessments/{d['assessment']['id']}", headers=headers
    ).json()["data"]["assessment"]["version"]
    c = client.post(
        f"/api/v1/assessments/{d['assessment']['id']}/complete",
        json={"expected_version": cur}, headers={**headers, "Idempotency-Key": _key()},
    )
    assert c.status_code == 200
    return headers, data


def _message(client, headers, session_id, text="接下来学什么？", expect=200):
    version = _sv(client, headers, session_id)
    r = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"text": text, "expected_version": version},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert r.status_code == expect, r.text
    return r.json()


def test_online_decision_recorded_as_llm(client, curriculum, db_factory):
    headers, data = _setup_ready(client, "在线决策")
    body = _message(client, headers, data["session"]["id"])
    decision = body["data"]["decision"]
    assert decision["planner_source"] == "llm"
    assert decision["model_id"] == "mock"
    assert decision["fallback_reason"] is None
    assert decision["action"] in {a["action"] for a in body["data"]["legal_actions"]}
    assert body["data"]["reply"]
    assert body["next_action"] is not None

    session_db = db_factory()
    with session_db.begin():
        usages = session_db.query(LLMUsage).all()
        assert len(usages) >= 1
        assert usages[0].ok is True
        assert usages[0].purpose == "teaching_decision"

    decisions = client.get(
        f"/api/v1/sessions/{data['session']['id']}/decisions", headers=headers
    ).json()["data"]["decisions"]
    assert len(decisions) == 1
    assert decisions[0]["planner_source"] == "llm"


def test_invalid_json_repair_then_llm(client, curriculum, monkeypatch):
    headers, data = _setup_ready(client, "修复成功")
    valid = json.dumps(
        {
            "action": "present_lesson",
            "target_id": None,
            "reason_code": "llm_repair",
            "evidence_ids": [],
            "student_message": "我们继续学习讲解。",
        },
        ensure_ascii=False,
    )
    provider = ScriptedProvider(["这不是JSON{{", valid])
    monkeypatch.setattr(coordinator_module, "build_gateway", lambda: LLMGateway(provider))
    body = _message(client, headers, data["session"]["id"])
    assert body["data"]["decision"]["planner_source"] == "llm"  # 第二次修复成功
    assert body["data"]["decision"]["reason_code"] == "llm_repair"


def test_a12_two_failures_fall_back_with_marker(client, curriculum, db_factory, monkeypatch):
    headers, data = _setup_ready(client, "全失败回退")
    provider = ScriptedProvider(["坏输出1", "坏输出2"])
    monkeypatch.setattr(coordinator_module, "build_gateway", lambda: LLMGateway(provider))
    body = _message(client, headers, data["session"]["id"])
    decision = body["data"]["decision"]
    assert decision["planner_source"] == "rule_fallback"
    assert decision["fallback_reason"]
    assert decision["action"] in {a["action"] for a in body["data"]["legal_actions"]}

    session_db = db_factory()
    with session_db.begin():
        usages = session_db.query(LLMUsage).all()
        assert len(usages) == 2  # 两次调用都有用量记录
        assert all(u.ok is False for u in usages)


def test_a12_timeout_falls_back(client, curriculum, monkeypatch):
    headers, data = _setup_ready(client, "超时回退")
    monkeypatch.setattr(
        coordinator_module, "build_gateway", lambda: LLMGateway(TimeoutProvider())
    )
    body = _message(client, headers, data["session"]["id"])
    decision = body["data"]["decision"]
    assert decision["planner_source"] == "rule_fallback"
    assert "timeout" in (decision["fallback_reason"] or "").lower()


def test_bogus_evidence_repaired(client, curriculum, monkeypatch):
    """LLM 虚构证据 ID → 校验拒绝 → 修复一次成功（A12）。"""
    headers, data = _setup_ready(client, "伪证据")
    bad = json.dumps(
        {
            "action": "present_lesson",
            "target_id": None,
            "reason_code": "llm",
            "evidence_ids": ["fabricated-evidence-id"],
            "student_message": "继续学习。",
        },
        ensure_ascii=False,
    )
    valid = json.dumps(
        {
            "action": "finish_session",
            "target_id": None,
            "reason_code": "llm_repair",
            "evidence_ids": [],
            "student_message": "今天到这里。",
        },
        ensure_ascii=False,
    )
    provider = ScriptedProvider([bad, valid])
    monkeypatch.setattr(coordinator_module, "build_gateway", lambda: LLMGateway(provider))
    body = _message(client, headers, data["session"]["id"])
    decision = body["data"]["decision"]
    assert decision["planner_source"] == "llm"  # 修复后走合法决策
    assert decision["evidence_ids"] == []


def test_a05_action_outside_legal_set_is_rejected(client, curriculum):
    """规则校验单元：不在合法集合的行动被拒绝（A05 的约束机制）。"""
    parsed = {"action": "assign_practice", "target_id": "t1", "evidence_ids": []}
    legal = [{"action": "offer_hint", "target_id": "e1", "reason_code": "open_exercise"}]
    decision, error = coordinator_module._validate_decision(
        None, student_id="s1", parsed=parsed, legal=legal
    )
    assert decision is None
    assert error == "action_not_legal:assign_practice"


def test_memory_facts_chain_and_references(client, curriculum, db_factory):
    headers, data = _setup_ready(client, "记忆链")
    # 第二轮诊断 → mastery_updated 再次发生 → 旧事实 superseded
    session_id = data["session"]["id"]
    version = _sv(client, headers, session_id)
    r = client.post(
        f"/api/v1/sessions/{session_id}/diagnosis",
        json={"expected_version": version}, headers={**headers, "Idempotency-Key": _key()},
    )
    d = r.json()["data"]
    # 第二轮诊断抽到 Q-C01-F5（screening 选择题）
    a = client.post(
        f"/api/v1/exercises/{d['exercise']['id']}/attempts",
        json={"answer": "B", "expected_version": d["exercise"]["version"]},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert a.status_code == 200
    cur = client.get(
        f"/api/v1/assessments/{d['assessment']['id']}", headers=headers
    ).json()["data"]["assessment"]["version"]
    client.post(
        f"/api/v1/assessments/{d['assessment']['id']}/complete",
        json={"expected_version": cur}, headers={**headers, "Idempotency-Key": _key()},
    )

    session_db = db_factory()
    with session_db.begin():
        facts = session_db.query(MemoryFact).order_by(MemoryFact.created_at).all()
        assert len(facts) == 2
        assert facts[0].status == "superseded"
        assert facts[1].status == "active"
        assert facts[0].evidence_event_ids
        assert "[C01]" in facts[1].content


def test_reflection_endpoint(client, curriculum):
    headers, data = _setup_ready(client, "小结")
    version = _sv(client, headers, data["session"]["id"])
    r = client.post(
        f"/api/v1/sessions/{data['session']['id']}/reflection",
        json={"text": "今天搞懂了平方。", "expected_version": version},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["summary"]["total_target"] == 1
    assert body["summary"]["evidence_count_total"] >= 1
    assert body["summary"]["recent_evidence_ids"]
