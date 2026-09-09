"""T05 路径与任务测试（A06/A07、双画像、锁定、预算、事件）。"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select

from app.infrastructure.models import Plan, Task


def _key() -> str:
    return f"t05-{uuid4().hex}"


def _headers_of(client, name: str):
    from tests.test_t04_flow import _key as _  # noqa: F401

    r = client.post(
        "/api/v1/demo-identities", json={"display_name": name},
        headers={"Idempotency-Key": _key()},
    )
    token = r.json()["data"]["token"]
    return {"Authorization": f"Bearer {token}"}


def _goal(client, headers, targets=None, daily=30):
    r = client.post(
        "/api/v1/goals",
        json={"course_id": "quadratic", "target_concept_ids": targets or [], "daily_minutes": daily},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


# 抽题稳定排序：screening 优先、按 id 升序，C01 前几轮依次为 F1 → F5 → X01 → ...
C01_ANSWERS = {
    "Q-C01-F1": "B",
    "Q-C01-F5": "B",
    "Q-C01-X01": "A",
    "Q-C01-F2": "1/4",
    "Q-C01-F3": "25",
    "Q-C01-F4": "B",
    "Q-C01-F6": "9/16",
    "Q-C01-F7": "-36",
    "Q-C01-F8": "C",
}
C01_WRONG = {
    "Q-C01-F1": "A",
    "Q-C01-F5": "A",
    "Q-C01-X01": "B",
    "Q-C01-F2": "1",
    "Q-C01-F3": "-25",
    "Q-C01-F4": "A",
    "Q-C01-F6": "999",
    "Q-C01-F7": "36",
    "Q-C01-F8": "A",
}


def _diagnose(client, headers, session_id, version, answer):
    """answer: 字符串（所有题同一答案）或 {question_id: answer} 映射。"""
    r = client.post(
        f"/api/v1/sessions/{session_id}/diagnosis",
        json={"expected_version": version},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assessment, exercise, question = data["assessment"], data["exercise"], data["question"]
    resolved = answer[question["id"]] if isinstance(answer, dict) else answer
    a = client.post(
        f"/api/v1/exercises/{exercise['id']}/attempts",
        json={"answer": resolved, "expected_version": exercise["version"]},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert a.status_code == 200, a.text
    current = client.get(
        f"/api/v1/assessments/{assessment['id']}", headers=headers
    ).json()["data"]["assessment"]["version"]
    c = client.post(
        f"/api/v1/assessments/{assessment['id']}/complete",
        json={"expected_version": current},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert c.status_code == 200, c.text
    return c.json()["data"]


def _fresh_session_version(client, headers, session_id):
    return client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()["resource_version"]


def test_a07_replan_without_change_keeps_version(client, curriculum):
    headers = _headers_of(client, "稳定学生")
    data = _goal(client, headers, targets=["C01"])
    session = data["session"]
    result = _diagnose(client, headers, session["id"], session["version"], "B")
    assert result["plan"]["version"] == 1
    assert result["plan"]["policy_version"] == "v1-rules"

    again = client.post(
        f"/api/v1/goals/{data['goal']['id']}/replan",
        json={"reason": "student_request", "expected_version": 1},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert again.status_code == 200, again.text
    body = again.json()["data"]
    assert body["changed"] is False
    assert body["plan"]["version"] == 1


def test_replan_conflict_on_stale_version(client, curriculum):
    headers = _headers_of(client, "过期计划")
    data = _goal(client, headers, targets=["C01"])
    _diagnose(client, headers, data["session"]["id"], data["session"]["version"], "B")
    stale = client.post(
        f"/api/v1/goals/{data['goal']['id']}/replan",
        json={"reason": "student_request", "expected_version": 0},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert stale.status_code == 409


def test_a06_budget_limits_tasks(client, curriculum):
    headers = _headers_of(client, "小预算")
    data = _goal(client, headers, targets=["C01", "C02"], daily=10)
    result = _diagnose(client, headers, data["session"]["id"], data["session"]["version"], "B")
    plan = result["plan"]

    tasks = client.get(
        f"/api/v1/goals/{data['goal']['id']}/tasks", headers=headers
    ).json()["data"]
    pending = sum(t["estimated_minutes"] for t in tasks["tasks"] if t["status"] in ("queued", "active"))
    assert pending <= 10
    assert tasks["within_budget"] is True
    # C01 后是锁定节点 C02（前置未掌握），预算内先给 C01 的任务
    concept_ids = {t["concept_id"] for t in tasks["tasks"]}
    assert concept_ids == {"C01"}
    _ = plan


def test_locked_nodes_have_no_tasks(client, curriculum):
    headers = _headers_of(client, "锁定检查")
    data = _goal(client, headers, targets=["C01", "C02", "C03"])
    _diagnose(client, headers, data["session"]["id"], data["session"]["version"], "B")

    path = client.get(f"/api/v1/goals/{data['goal']['id']}/path", headers=headers).json()["data"]
    statuses = {n["concept_id"]: n for n in path["nodes"]}
    assert statuses["C02"]["status"] == "locked"
    assert "前置未掌握" in statuses["C02"]["reason"]
    assert statuses["C02"]["tasks"] == []
    assert statuses["C01"]["status"] in ("developing", "needs_support", "unassessed")


def test_two_profiles_get_different_paths(client, curriculum):
    headers_a = _headers_of(client, "画像甲")
    headers_b = _headers_of(client, "画像乙")
    data_a = _goal(client, headers_a, targets=["C01"])
    data_b = _goal(client, headers_b, targets=["C01"])

    # 甲：两轮全错 → needs_support
    for _ in range(2):
        version = _fresh_session_version(client, headers_a, data_a["session"]["id"])
        _diagnose(client, headers_a, data_a["session"]["id"], version, C01_WRONG)
    # 乙：三轮全对 → mastered
    for _ in range(3):
        version = _fresh_session_version(client, headers_b, data_b["session"]["id"])
        _diagnose(client, headers_b, data_b["session"]["id"], version, C01_ANSWERS)

    path_a = client.get(f"/api/v1/goals/{data_a['goal']['id']}/path", headers=headers_a).json()["data"]
    path_b = client.get(f"/api/v1/goals/{data_b['goal']['id']}/path", headers=headers_b).json()["data"]

    status_a = {n["concept_id"]: n["status"] for n in path_a["nodes"]}
    status_b = {n["concept_id"]: n["status"] for n in path_b["nodes"]}
    assert status_a["C01"] == "needs_support"
    assert status_b["C01"] == "mastered"

    tasks_a = client.get(f"/api/v1/goals/{data_a['goal']['id']}/tasks", headers=headers_a).json()["data"]
    tasks_b = client.get(f"/api/v1/goals/{data_b['goal']['id']}/tasks", headers=headers_b).json()["data"]
    pending_a = [t for t in tasks_a["tasks"] if t["status"] in ("queued", "active")]
    pending_b = [t for t in tasks_b["tasks"] if t["status"] in ("queued", "active")]
    assert pending_a and all(t["concept_id"] == "C01" for t in pending_a)
    assert pending_b == []  # 乙已掌握且未到期，无待办


def test_mastery_change_bumps_plan_version_with_event(client, curriculum, db_factory):
    headers = _headers_of(client, "升版检查")
    data = _goal(client, headers, targets=["C01", "C02"])
    session = data["session"]
    # 第一轮诊断完成 → 计划 v1（C01 developing，C02 锁定）
    _diagnose(client, headers, session["id"], session["version"], C01_ANSWERS)
    plan_v1 = client.get(
        f"/api/v1/goals/{data['goal']['id']}/path", headers=headers
    ).json()["data"]["plan"]["version"]
    assert plan_v1 == 1

    # 第二轮：C01 0.75 仍 developing，顺序不变 → 不升版（A07）
    version = _fresh_session_version(client, headers, session["id"])
    _diagnose(client, headers, session["id"], version, C01_ANSWERS)
    plan_still = client.get(
        f"/api/v1/goals/{data['goal']['id']}/path", headers=headers
    ).json()["data"]["plan"]["version"]
    assert plan_still == 1

    # 第三轮：C01 0.8 mastered → C02 解锁进入工作序列 → 顺序真正变化 → v2
    version = _fresh_session_version(client, headers, session["id"])
    _diagnose(client, headers, session["id"], version, C01_ANSWERS)
    plan_v2 = client.get(
        f"/api/v1/goals/{data['goal']['id']}/path", headers=headers
    ).json()["data"]["plan"]["version"]
    assert plan_v2 == 2

    session_db = db_factory()
    with session_db.begin():
        versions = sorted(
            p.version for p in session_db.execute(
                select(Plan).where(Plan.goal_id == data["goal"]["id"])
            ).scalars().all()
        )
        assert versions == [1, 2]


def test_tasks_date_filter(client, curriculum):
    headers = _headers_of(client, "日期过滤")
    data = _goal(client, headers, targets=["C01"])
    _diagnose(client, headers, data["session"]["id"], data["session"]["version"], "B")

    today = client.get(
        f"/api/v1/goals/{data['goal']['id']}/tasks", headers=headers
    ).json()["data"]
    assert today["tasks"]
    empty = client.get(
        f"/api/v1/goals/{data['goal']['id']}/tasks",
        params={"date": "2000-01-01"}, headers=headers,
    ).json()["data"]
    assert empty["tasks"] == []
    bad = client.get(
        f"/api/v1/goals/{data['goal']['id']}/tasks",
        params={"date": "not-a-date"}, headers=headers,
    )
    assert bad.status_code == 422
