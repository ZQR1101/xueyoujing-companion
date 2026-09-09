"""T10-B AI 学情诊断测试。

验收（规划书）：正常、无思路、虚构 ID、非法 JSON、超时五种情况均有结果；
AI 诊断与确定性评分分开保存；失败时使用规则回退并标记 rule_fallback。
"""

from __future__ import annotations

import json
from uuid import uuid4

from app.infrastructure.llm.gateway import LLMGateway, ScriptedProvider, TimeoutProvider
from app.infrastructure.models import DiagnosisReport, LLMUsage, MasteryState
from app.services import diagnosis_report as report_module


def _key() -> str:
    return f"t10b-{uuid4().hex}"


def _headers_of(client, name: str):
    r = client.post(
        "/api/v1/demo-identities", json={"display_name": name},
        headers={"Idempotency-Key": _key()},
    )
    return {"Authorization": f"Bearer {r.json()['data']['token']}"}


def _goal(client, headers, targets):
    r = client.post(
        "/api/v1/goals",
        json={"course_id": "quadratic", "target_concept_ids": targets, "daily_minutes": 30},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _diagnosis(client, headers, answer: str) -> None:
    """完成诊断（单概念目标一题），answer 为首题作答。"""
    data = _goal(client, headers, targets=["C01"])
    session_id = data["session"]["id"]
    version = client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()["resource_version"]
    d = client.post(
        f"/api/v1/sessions/{session_id}/diagnosis",
        json={"expected_version": version}, headers={**headers, "Idempotency-Key": _key()},
    ).json()["data"]
    client.post(
        f"/api/v1/exercises/{d['exercise']['id']}/attempts",
        json={"answer": answer, "expected_version": d["exercise"]["version"]},
        headers={**headers, "Idempotency-Key": _key()},
    )
    cur = client.get(
        f"/api/v1/assessments/{d['assessment']['id']}", headers=headers
    ).json()["data"]["assessment"]["version"]
    c = client.post(
        f"/api/v1/assessments/{d['assessment']['id']}/complete",
        json={"expected_version": cur}, headers={**headers, "Idempotency-Key": _key()},
    )
    assert c.status_code == 200
    return data


def _second_eligible(client, headers, data: dict) -> None:
    """练习任务首答独立正确 → 第 2 份有效证据。"""
    session_id = data["session"]["id"]
    sv = client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()["resource_version"]
    lesson = client.post(
        f"/api/v1/sessions/{session_id}/start-next",
        json={"expected_version": sv}, headers={**headers, "Idempotency-Key": _key()},
    ).json()["data"]
    if lesson["task"]["type"] == "lesson":
        ack = client.post(
            f"/api/v1/tasks/{lesson['task']['id']}/acknowledge",
            json={"expected_version": lesson["task"]["version"]},
            headers={**headers, "Idempotency-Key": _key()},
        )
        assert ack.status_code == 200
        sv = client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()["resource_version"]
        practice = client.post(
            f"/api/v1/sessions/{session_id}/start-next",
            json={"expected_version": sv}, headers={**headers, "Idempotency-Key": _key()},
        ).json()["data"]
    else:
        practice = lesson
    r = client.post(
        f"/api/v1/exercises/{practice['exercise']['id']}/attempts",
        json={"answer": "B", "expected_version": practice["exercise"]["version"]},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert r.status_code == 200
    assert r.json()["data"]["evidence"]["eligible"] is True


_VALID = json.dumps(
    {
        "summary": "基础代入扎实，符号处理需要进一步确认。",
        "observations": [{"concept_id": "C01", "title": "已观察到", "detail": "代入计算稳定。"}],
        "hypotheses": [{"concept_id": None, "title": "仍需确认", "detail": "符号规则是否稳定。"}],
        "recommended_probe": {"concept_id": "C01", "summary": "先做一道符号辨析补测。"},
        "evidence_ids": [],
    },
    ensure_ascii=False,
)


def test_report_insufficient_evidence_no_llm(client, curriculum, monkeypatch):
    """证据不足：不调用模型，返回可解释规则结果（无思路场景的底座）。"""
    headers = _headers_of(client, "诊断证据不足")
    data = _goal(client, headers, targets=["C01"])
    goal_id = data["goal"]["id"]
    called = {"n": 0}

    def _fail():
        called["n"] += 1
        raise AssertionError("证据不足时不应调用模型")

    monkeypatch.setattr(report_module, "build_gateway", _fail)
    r = client.post(
        f"/api/v1/goals/{goal_id}/diagnosis-report",
        json=None,
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["status"] == "insufficient_evidence"
    assert body["planner_source"] == "rule_fallback"
    assert body["fallback_reason"] == "insufficient_evidence"
    assert called["n"] == 0


def _goal_id(client, headers) -> str:
    overview = client.get("/api/v1/me/overview", headers=headers).json()["data"]
    return overview["goals"][0]["goal"]["id"]


def test_report_llm_normal(client, curriculum, monkeypatch):
    """正常：模型输出合法 → planner_source=llm；掌握度不被改动（分开保存）。"""
    headers = _headers_of(client, "诊断正常")
    data = _diagnosis(client, headers, "B")
    _second_eligible(client, headers, data)
    goal_id = _goal_id(client, headers)

    r0 = client.get("/api/v1/me/overview", headers=headers).json()["data"]
    mastery_before = r0["goals"][0]["mastery"]

    monkeypatch.setattr(report_module, "build_gateway", lambda: LLMGateway(ScriptedProvider([_VALID])))
    r = client.post(
        f"/api/v1/goals/{goal_id}/diagnosis-report",
        json={},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["planner_source"] == "llm"
    assert body["status"] == "ok"
    assert body["observations"][0]["concept_id"] == "C01"
    assert body["recommended_probe"]["concept_id"] == "C01"

    r1 = client.get("/api/v1/me/overview", headers=headers).json()["data"]
    assert r1["goals"][0]["mastery"] == mastery_before  # 确定性评分未被 AI 诊断改动

    got = client.get(f"/api/v1/goals/{goal_id}/diagnosis-report", headers=headers).json()["data"]
    assert got["planner_source"] == "llm"
    assert got["report_id"] == body["report_id"]


def test_report_fabricated_concept_repair_then_fallback(client, curriculum, monkeypatch):
    """虚构 ID：修复一次仍虚构 → 规则回退并标记原因。"""
    headers = _headers_of(client, "诊断虚构ID")
    data = _diagnosis(client, headers, "B")
    _second_eligible(client, headers, data)
    goal_id = _goal_id(client, headers)

    bad = _VALID.replace('"C01"', '"C99"')
    monkeypatch.setattr(
        report_module, "build_gateway", lambda: LLMGateway(ScriptedProvider([bad, bad]))
    )
    r = client.post(
        f"/api/v1/goals/{goal_id}/diagnosis-report",
        json={},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["planner_source"] == "rule_fallback"
    assert "fabricated_concept_id" in body["fallback_reason"]
    assert body["status"] == "ok"  # 规则结果仍可解释、可用
    assert body["observations"]  # 规则结果非空


def test_report_invalid_json_fallback(client, curriculum, monkeypatch):
    """非法 JSON：修复一次仍非法 → 规则回退。"""
    headers = _headers_of(client, "诊断坏JSON")
    data = _diagnosis(client, headers, "B")
    _second_eligible(client, headers, data)
    goal_id = _goal_id(client, headers)

    monkeypatch.setattr(
        report_module, "build_gateway", lambda: LLMGateway(ScriptedProvider(["{{不是JSON", "还是{{不是"]))
    )
    r = client.post(
        f"/api/v1/goals/{goal_id}/diagnosis-report",
        json={},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["planner_source"] == "rule_fallback"
    assert body["fallback_reason"]
    assert body["summary"]


def test_report_empty_diagnosis_fallback(client, curriculum, monkeypatch):
    """无思路：模型输出合法 JSON 但无任何诊断内容 → 修复后回退。"""
    headers = _headers_of(client, "诊断无思路")
    data = _diagnosis(client, headers, "B")
    _second_eligible(client, headers, data)
    goal_id = _goal_id(client, headers)

    empty = json.dumps(
        {"summary": "无", "observations": [], "hypotheses": [],
         "recommended_probe": {"concept_id": None, "summary": "无"}, "evidence_ids": []},
        ensure_ascii=False,
    )
    monkeypatch.setattr(
        report_module, "build_gateway", lambda: LLMGateway(ScriptedProvider([empty, empty]))
    )
    r = client.post(
        f"/api/v1/goals/{goal_id}/diagnosis-report",
        json={},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["planner_source"] == "rule_fallback"
    assert body["fallback_reason"] == "empty_diagnosis"


def test_report_timeout_fallback(client, curriculum, monkeypatch):
    """超时：直接规则回退，不阻塞。"""
    headers = _headers_of(client, "诊断超时")
    data = _diagnosis(client, headers, "B")
    _second_eligible(client, headers, data)
    goal_id = _goal_id(client, headers)

    monkeypatch.setattr(
        report_module, "build_gateway", lambda: LLMGateway(TimeoutProvider())
    )
    r = client.post(
        f"/api/v1/goals/{goal_id}/diagnosis-report",
        json={},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["planner_source"] == "rule_fallback"
    assert "TimeoutException" in body["fallback_reason"]


def test_report_persist_and_usage(client, curriculum, db_factory, monkeypatch):
    """诊断记录与用量分开持久化；重放相同输入得到一致规则结果。"""
    headers = _headers_of(client, "诊断记录")
    data = _diagnosis(client, headers, "B")
    _second_eligible(client, headers, data)
    goal_id = _goal_id(client, headers)

    monkeypatch.setattr(
        report_module, "build_gateway", lambda: LLMGateway(ScriptedProvider([_VALID, _VALID]))
    )
    r1 = client.post(
        f"/api/v1/goals/{goal_id}/diagnosis-report",
        json={}, headers={**headers, "Idempotency-Key": _key()},
    )
    r2 = client.post(
        f"/api/v1/goals/{goal_id}/diagnosis-report",
        json={}, headers={**headers, "Idempotency-Key": _key()},
    )
    assert r1.status_code == r2.status_code == 200

    session_db = db_factory()
    with session_db.begin():
        reports = session_db.query(DiagnosisReport).all()
        assert len(reports) == 2
        assert all(rep.planner_source == "llm" for rep in reports)
        usages = session_db.query(LLMUsage).all()
        assert all(u.purpose == "diagnosis_report" for u in usages)
        assert len(usages) == 2
        mastery = session_db.query(MasteryState).all()
        assert len(mastery) == 1  # AI 诊断不产生/修改掌握状态


def test_report_ownership(client, curriculum, monkeypatch):
    """学生 B 不能读取/生成学生 A 的诊断（404，无数据泄露）。"""
    headers_a = _headers_of(client, "诊断归属A")
    data = _diagnosis(client, headers_a, "B")
    _second_eligible(client, headers_a, data)
    goal_a = _goal_id(client, headers_a)
    monkeypatch.setattr(
        report_module, "build_gateway", lambda: LLMGateway(ScriptedProvider([_VALID]))
    )
    assert client.post(
        f"/api/v1/goals/{goal_a}/diagnosis-report",
        json={}, headers={**headers_a, "Idempotency-Key": _key()},
    ).status_code == 200

    headers_b = _headers_of(client, "诊断归属B")
    r = client.get(f"/api/v1/goals/{goal_a}/diagnosis-report", headers=headers_b)
    assert r.status_code == 404
    r2 = client.post(
        f"/api/v1/goals/{goal_a}/diagnosis-report",
        json={}, headers={**headers_b, "Idempotency-Key": _key()},
    )
    assert r2.status_code == 404
