"""T11-B LLM 路径决策测试。

覆盖：正常选择、伪造 target 修复一次、非法 JSON、超时、候选为空 no_legal_action、
insert_probe 真实调整（任务集合变化才升 Plan.version）、无变化不升版、
版本冲突 409、归属校验、相同输入重放（input_state_hash 一致）。
"""

from __future__ import annotations

import json
from uuid import uuid4

from app.infrastructure.llm.gateway import LLMGateway, ScriptedProvider, TimeoutProvider
from app.infrastructure.models import PathDecision
from app.services import path_decision as decision_module


def _key() -> str:
    return f"t11b-{uuid4().hex}"


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


def _post_decision(client, headers, goal_id, expected_version):
    return client.post(
        f"/api/v1/goals/{goal_id}/path-decision",
        json={"expected_version": expected_version},
        headers={**headers, "Idempotency-Key": _key()},
    )


def _plan_version(client, headers, goal_id) -> int:
    return client.get(f"/api/v1/goals/{goal_id}/path", headers=headers).json()["resource_version"]


def test_decision_continues_plan_no_version_bump(client, curriculum):
    """正常（mock 提供者选候选首选）：继续计划，无实际变化不升版。"""
    headers = _headers_of(client, "决策继续")
    data = _goal(client, headers, targets=["C01"])
    goal_id = data["goal"]["id"]
    session_id = data["session"]["id"]
    version = client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()["resource_version"]
    d = client.post(
        f"/api/v1/sessions/{session_id}/diagnosis",
        json={"expected_version": version}, headers={**headers, "Idempotency-Key": _key()},
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

    r = _post_decision(client, headers, goal_id, expected_version=1)
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["planner_source"] == "llm"  # mock 提供者参与选择，model_id=mock 可见
    assert body["model_id"] == "mock"
    assert body["selected_action"]["action"] == "continue_task"
    assert body["changed"] is False
    assert body["plan_after"]["version"] == 1  # 无变化不升版（A07）
    assert body["candidate_actions"]  # 候选集合来自规则层并随决策持久化

    got = client.get(f"/api/v1/goals/{goal_id}/path-decision", headers=headers).json()["data"]
    assert got["decision_id"] == body["decision_id"]
    assert got["input_state_hash"]


def test_decision_insert_probe_adjusts_plan(client, curriculum, db_factory, monkeypatch):
    """重复错误 → 规则候选含 insert_probe；选中后真实补任务，任务集合变化升版。"""
    from app.infrastructure.models import Attempt, Exercise, Task

    headers = _headers_of(client, "决策补测")
    data = _goal(client, headers, targets=["C01"])
    goal_id = data["goal"]["id"]
    goal_pk = data["goal"]["id"]
    student_id = client.get("/api/v1/me/overview", headers=headers).json()["data"]["student"]["id"]
    session_id = data["session"]["id"]

    # 诊断答错（第 1 道不同题的错误）→ 计划 v1：lesson + practice 排队
    version = client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()["resource_version"]
    d = client.post(
        f"/api/v1/sessions/{session_id}/diagnosis",
        json={"expected_version": version}, headers={**headers, "Idempotency-Key": _key()},
    ).json()["data"]
    client.post(
        f"/api/v1/exercises/{d['exercise']['id']}/attempts",
        json={"answer": "C", "expected_version": d["exercise"]["version"]},
        headers={**headers, "Idempotency-Key": _key()},
    )
    cur = client.get(
        f"/api/v1/assessments/{d['assessment']['id']}", headers=headers
    ).json()["data"]["assessment"]["version"]
    client.post(
        f"/api/v1/assessments/{d['assessment']['id']}/complete",
        json={"expected_version": cur}, headers={**headers, "Idempotency-Key": _key()},
    )

    # 构造 repeated_error 状态：另一道不同题的错答；并把排队练习取消（模拟已消费）
    session_db = db_factory()
    with session_db.begin():
        ex = Exercise(
            student_id=student_id, assessment_id=d["assessment"]["id"], task_id=None,
            question_id="Q-C01-F2", hint_level=0, solution_seen=False, status="closed", version=1,
        )
        session_db.add(ex)
        session_db.flush()
        session_db.add(
            Attempt(
                exercise_id=ex.id, student_id=student_id, answer="9",
                grade="incorrect", hint_level_at_submission=0,
            )
        )
        queued = (
            session_db.query(Task)
            .filter(
                Task.student_id == student_id, Task.goal_id == goal_pk,
                Task.concept_id == "C01", Task.type == "practice", Task.status == "queued",
            )
            .first()
        )
        if queued is not None:
            queued.status = "cancelled"
            queued.version += 1

    import json

    pick_probe = json.dumps(
        {"action": "insert_probe", "target_id": "C01",
         "reason": "最近两道题出现相似的符号问题，先补测确认是否为稳定性问题。", "evidence_ids": []},
        ensure_ascii=False,
    )
    monkeypatch.setattr(
        decision_module, "build_gateway", lambda: LLMGateway(ScriptedProvider([pick_probe]))
    )
    current_version = _plan_version(client, headers, goal_id)
    r = _post_decision(client, headers, goal_id, expected_version=current_version)
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["candidate_actions"][0]["action"] == "insert_probe"
    assert body["selected_action"]["action"] == "insert_probe"
    assert body["planner_source"] == "llm"
    assert body["status"] == "adjusted"
    assert body["changed"] is True
    assert body["plan_before"]["version"] == current_version
    assert body["plan_after"]["version"] == current_version + 1  # 任务集合真实变化 → 升版
    assert body["current_task"]["concept_id"] == "C01"
    assert body["current_task"]["type"] == "practice"

    session_db = db_factory()
    with session_db.begin():
        row = session_db.query(PathDecision).order_by(PathDecision.created_at.desc()).first()
        assert row.changed is True
        assert row.candidate_actions
        assert row.model_id == "scripted"


def test_decision_fabricated_target_repair_then_rule_fallback(client, curriculum, monkeypatch):
    """伪造 target：修复一次仍不合法 → 规则首选行动 + rule_fallback 标记，不伪造任务。"""
    headers = _headers_of(client, "决策伪造")
    data = _goal(client, headers, targets=["C01"])
    goal_id = data["goal"]["id"]
    session_id = data["session"]["id"]
    version = client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()["resource_version"]
    d = client.post(
        f"/api/v1/sessions/{session_id}/diagnosis",
        json={"expected_version": version}, headers={**headers, "Idempotency-Key": _key()},
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

    bad = json.dumps(
        {"action": "continue_task", "target_id": "fabricated-task-id",
         "reason": "直接继续", "evidence_ids": []},
        ensure_ascii=False,
    )
    monkeypatch.setattr(decision_module, "build_gateway", lambda: LLMGateway(ScriptedProvider([bad, bad])))
    r = _post_decision(client, headers, goal_id, expected_version=1)
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["planner_source"] == "rule_fallback"
    assert "action_target_not_legal" in body["fallback_reason"]
    assert body["selected_action"]["action"] == "continue_task"  # 规则首选
    assert body["selected_action"]["target_id"] != "fabricated-task-id"
    assert body["changed"] is False


def test_decision_timeout_fallback(client, curriculum, monkeypatch):
    """超时：直接使用规则首选行动并标记。"""
    headers = _headers_of(client, "决策超时")
    data = _goal(client, headers, targets=["C01"])
    goal_id = data["goal"]["id"]
    session_id = data["session"]["id"]
    version = client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()["resource_version"]
    d = client.post(
        f"/api/v1/sessions/{session_id}/diagnosis",
        json={"expected_version": version}, headers={**headers, "Idempotency-Key": _key()},
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

    monkeypatch.setattr(decision_module, "build_gateway", lambda: LLMGateway(TimeoutProvider()))
    r = _post_decision(client, headers, goal_id, expected_version=1)
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["planner_source"] == "rule_fallback"
    assert "TimeoutException" in body["fallback_reason"]
    assert body["selected_action"]["action"] == "continue_task"


def test_decision_no_legal_action(client, curriculum):
    """候选为空（尚无计划）：no_legal_action，不伪造任务。"""
    headers = _headers_of(client, "决策空候选")
    data = _goal(client, headers, targets=["C01"])
    goal_id = data["goal"]["id"]

    r = _post_decision(client, headers, goal_id, expected_version=0)
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["status"] == "no_legal_action"
    assert body["candidate_actions"] == []
    assert body["changed"] is False
    assert body["current_task"] is None


def test_decision_version_conflict(client, curriculum):
    """路径版本冲突：409，不覆盖其他版本。"""
    headers = _headers_of(client, "决策冲突")
    data = _goal(client, headers, targets=["C01"])
    goal_id = data["goal"]["id"]
    r = _post_decision(client, headers, goal_id, expected_version=99)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "version_conflict"


def test_decision_ownership(client, curriculum):
    """学生 B 操作学生 A 的目标：404。"""
    headers_a = _headers_of(client, "决策归属A")
    data = _goal(client, headers_a, targets=["C01"])
    goal_a = data["goal"]["id"]
    headers_b = _headers_of(client, "决策归属B")
    assert _post_decision(client, headers_b, goal_a, expected_version=0).status_code == 404
    assert client.get(f"/api/v1/goals/{goal_a}/path-decision", headers=headers_b).status_code == 404


def test_decision_replay_same_hash(client, curriculum):
    """重放：相同输入、规则版本和候选集合 → input_state_hash 一致。"""
    headers = _headers_of(client, "决策重放")
    data = _goal(client, headers, targets=["C01"])
    goal_id = data["goal"]["id"]
    session_id = data["session"]["id"]
    version = client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()["resource_version"]
    d = client.post(
        f"/api/v1/sessions/{session_id}/diagnosis",
        json={"expected_version": version}, headers={**headers, "Idempotency-Key": _key()},
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

    r1 = _post_decision(client, headers, goal_id, expected_version=1).json()["data"]
    r2 = _post_decision(client, headers, goal_id, expected_version=1).json()["data"]
    assert r1["input_state_hash"] == r2["input_state_hash"]
    assert r1["candidate_actions"] == r2["candidate_actions"]
    assert r2["plan_after"]["version"] == 1  # 两次均无实际变化，不升版
