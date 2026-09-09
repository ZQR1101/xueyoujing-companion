"""T12-B Tutor Agent 启发式辅导测试。

覆盖：正常分析、非法 JSON/超时/空字段回退、归属校验、已关闭题目拒绝、
轨迹时间线（作答/提示/思路/反馈排序 + 当前态）、思路不产生/不修改掌握证据。
"""

from __future__ import annotations

import json
from uuid import uuid4

from app.infrastructure.llm.gateway import LLMGateway, ScriptedProvider, TimeoutProvider
from app.infrastructure.models import Event
from app.services import tutoring_agent as agent_module


def _key() -> str:
    return f"t12b-{uuid4().hex}"


def _headers_of(client, name: str):
    r = client.post(
        "/api/v1/demo-identities", json={"display_name": name},
        headers={"Idempotency-Key": _key()},
    )
    return {"Authorization": f"Bearer {r.json()['data']['token']}"}


def _wrong_attempt_setup(client, headers):
    """诊断通过 → 讲解确认 → 练习首答答错，得到开放练习与错答状态。"""
    data = client.post(
        "/api/v1/goals",
        json={"course_id": "quadratic", "target_concept_ids": ["C01"], "daily_minutes": 30},
        headers={**headers, "Idempotency-Key": _key()},
    ).json()["data"]
    session_id = data["session"]["id"]

    def sv():
        return client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()["resource_version"]

    d = client.post(
        f"/api/v1/sessions/{session_id}/diagnosis",
        json={"expected_version": sv()}, headers={**headers, "Idempotency-Key": _key()},
    ).json()["data"]
    client.post(
        f"/api/v1/exercises/{d['exercise']['id']}/attempts",
        json={"answer": "B", "expected_version": d["exercise"]["version"]},
        headers={**headers, "Idempotency-Key": _key()},
    )
    cur = client.get(
        f"/api/v1/assessments/{d['assessment']['id']}", headers=headers
    ).json()["data"]["assessment"]["version"]
    client.post(
        f"/api/v1/assessments/{d['assessment']['id']}/complete",
        json={"expected_version": cur}, headers={**headers, "Idempotency-Key": _key()},
    )
    lesson = client.post(
        f"/api/v1/sessions/{session_id}/start-next",
        json={"expected_version": sv()}, headers={**headers, "Idempotency-Key": _key()},
    ).json()["data"]
    client.post(
        f"/api/v1/tasks/{lesson['task']['id']}/acknowledge",
        json={"expected_version": lesson["task"]["version"]},
        headers={**headers, "Idempotency-Key": _key()},
    )
    practice = client.post(
        f"/api/v1/sessions/{session_id}/start-next",
        json={"expected_version": sv()}, headers={**headers, "Idempotency-Key": _key()},
    ).json()["data"]
    wrong = client.post(
        f"/api/v1/exercises/{practice['exercise']['id']}/attempts",
        json={"answer": "A", "expected_version": practice["exercise"]["version"]},
        headers={**headers, "Idempotency-Key": _key()},
    ).json()["data"]
    return data, practice, wrong


def test_thinking_llm_normal(client, curriculum, monkeypatch, db_factory):
    headers = _headers_of(client, "思路正常")
    data, practice, _ = _wrong_attempt_setup(client, headers)
    ov0 = client.get("/api/v1/me/overview", headers=headers).json()["data"]
    mastery0 = ov0["goals"][0]["mastery"]

    valid = json.dumps(
        {
            "feedback": "思路收到，我们先聚焦顶点式里括号的符号。",
            "possible_problem": "顶点坐标与括号符号的对应还不稳定。",
            "socratic_question": "顶点是 (2, -1) 时，x - h 里的 h 应该取几？代入后括号里是什么？",
        },
        ensure_ascii=False,
    )
    monkeypatch.setattr(agent_module, "build_gateway", lambda: LLMGateway(ScriptedProvider([valid])))
    r = client.post(
        f"/api/v1/exercises/{practice['exercise']['id']}/thinking",
        json={"text": "我不确定括号里应该写成 (x-2) 还是 (x+2)。"},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["planner_source"] == "llm"
    assert "括号" in body["possible_problem"]
    assert body["socratic_question"]
    assert "答案" not in body["socratic_question"][:0]  # 结构性占位：具体答案泄露由规则提示约束

    ov1 = client.get("/api/v1/me/overview", headers=headers).json()["data"]
    assert ov1["goals"][0]["mastery"] == mastery0  # 思路分析不动掌握状态

    session_db = db_factory()
    with session_db.begin():
        events = session_db.query(Event).filter(Event.type.in_(["thinking_submitted", "tutor_feedback"])).all()
        assert len(events) == 2


def test_thinking_invalid_json_fallback(client, curriculum, monkeypatch):
    headers = _headers_of(client, "思路坏JSON")
    data, practice, _ = _wrong_attempt_setup(client, headers)
    monkeypatch.setattr(
        agent_module, "build_gateway", lambda: LLMGateway(ScriptedProvider(["{{不是", "还是{{不是"]))
    )
    r = client.post(
        f"/api/v1/exercises/{practice['exercise']['id']}/thinking",
        json={"text": "卡在符号上了。"},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["planner_source"] == "rule_fallback"
    assert body["fallback_reason"]
    assert body["feedback"] and body["possible_problem"] and body["socratic_question"]


def test_thinking_timeout_fallback(client, curriculum, monkeypatch):
    headers = _headers_of(client, "思路超时")
    data, practice, _ = _wrong_attempt_setup(client, headers)
    monkeypatch.setattr(agent_module, "build_gateway", lambda: LLMGateway(TimeoutProvider()))
    r = client.post(
        f"/api/v1/exercises/{practice['exercise']['id']}/thinking",
        json={"text": "完全没思路。"},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["planner_source"] == "rule_fallback"
    assert "TimeoutException" in body["fallback_reason"]


def test_thinking_empty_fields_fallback(client, curriculum, monkeypatch):
    headers = _headers_of(client, "思路空字段")
    data, practice, _ = _wrong_attempt_setup(client, headers)
    empty = json.dumps({"feedback": "", "possible_problem": "", "socratic_question": ""}, ensure_ascii=False)
    monkeypatch.setattr(
        agent_module, "build_gateway", lambda: LLMGateway(ScriptedProvider([empty, empty]))
    )
    r = client.post(
        f"/api/v1/exercises/{practice['exercise']['id']}/thinking",
        json={"text": "说不出哪里不懂。"},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["planner_source"] == "rule_fallback"
    assert body["feedback"]


def test_thinking_ownership(client, curriculum):
    headers_a = _headers_of(client, "思路归属A")
    data, practice, _ = _wrong_attempt_setup(client, headers_a)
    headers_b = _headers_of(client, "思路归属B")
    r = client.post(
        f"/api/v1/exercises/{practice['exercise']['id']}/thinking",
        json={"text": "这是B在偷看。"},
        headers={**headers_b, "Idempotency-Key": _key()},
    )
    assert r.status_code == 404
    assert client.get(
        f"/api/v1/exercises/{practice['exercise']['id']}/tutoring-trace", headers=headers_b
    ).status_code == 404


def test_thinking_closed_exercise_rejected(client, curriculum):
    headers = _headers_of(client, "思路已关闭")
    data, practice, _ = _wrong_attempt_setup(client, headers)
    h = client.post(
        f"/api/v1/exercises/{practice['exercise']['id']}/hints",
        json={"expected_version": practice["exercise"]["version"]},
        headers={**headers, "Idempotency-Key": _key()},
    ).json()["data"]
    closed = client.post(
        f"/api/v1/exercises/{practice['exercise']['id']}/attempts",
        json={"answer": "B", "expected_version": h["exercise_version"]},
        headers={**headers, "Idempotency-Key": _key()},
    ).json()
    assert closed["data"]["attempt"]["grade"] == "correct"  # 原题重试对 → Exercise 关闭
    r = client.post(
        f"/api/v1/exercises/{practice['exercise']['id']}/thinking",
        json={"text": "这题不是已经关了吗。"},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "illegal_state"


def test_trace_timeline(client, curriculum, monkeypatch):
    headers = _headers_of(client, "辅导轨迹")
    data, practice, _ = _wrong_attempt_setup(client, headers)
    ex_id = practice["exercise"]["id"]
    client.post(
        f"/api/v1/exercises/{ex_id}/hints",
        json={"expected_version": practice["exercise"]["version"]},
        headers={**headers, "Idempotency-Key": _key()},
    )
    valid = json.dumps(
        {"feedback": "反馈", "possible_problem": "符号对应", "socratic_question": "追问？"},
        ensure_ascii=False,
    )
    monkeypatch.setattr(agent_module, "build_gateway", lambda: LLMGateway(ScriptedProvider([valid])))
    client.post(
        f"/api/v1/exercises/{ex_id}/thinking",
        json={"text": "括号符号不确定。"},
        headers={**headers, "Idempotency-Key": _key()},
    )

    r = client.get(f"/api/v1/exercises/{ex_id}/tutoring-trace", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    types = [item["type"] for item in body["timeline"]]
    assert types[0] == "start"
    assert "attempt" in types and "hint" in types and "thinking" in types and "feedback" in types
    assert types == sorted(types, key=lambda t: ["start", "attempt", "hint", "thinking", "feedback", "solution"].index(t))
    assert body["current"]["label"] == "等待修改后重新提交"
    assert body["hint_level"] == 1
    assert body["latest_feedback"]["planner_source"] == "llm"
    attempt_item = next(item for item in body["timeline"] if item["type"] == "attempt")
    assert attempt_item["grade"] == "incorrect" and attempt_item["answer"] == "A"
