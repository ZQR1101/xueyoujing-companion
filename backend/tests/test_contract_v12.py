"""合同 v1.2 修订（R6/R7/R8）回归测试。"""

from __future__ import annotations

import json
import uuid

from sqlalchemy import select

from app.infrastructure.curriculum_import import import_curriculum
from app.infrastructure.models import Event, Question
from app.services import coordinator as coordinator_module
from app.infrastructure.llm.gateway import LLMGateway, ScriptedProvider, TimeoutProvider  # noqa: F401


def _key() -> str:
    return f"v12-{uuid.uuid4().hex}"


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


def _start_next(client, headers, session_id):
    version = _sv(client, headers, session_id)
    r = client.post(
        f"/api/v1/sessions/{session_id}/start-next",
        json={"expected_version": version}, headers={**headers, "Idempotency-Key": _key()},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _message(client, headers, session_id, text="接下来做什么？", expect=200):
    version = _sv(client, headers, session_id)
    r = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"text": text, "expected_version": version},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert r.status_code == expect, r.text
    return r.json()


def test_r6_private_solution_stored_and_isolated(client, curriculum, db_factory):
    session = db_factory()
    with session.begin():
        import_curriculum(session)

    with session.begin():
        q = session.get(Question, "Q-C01-F1")
        assert q.private_solution and "(-3)×(-3)" in q.private_solution
        assert q.private_solution not in q.private_hints  # 解析与提示互相独立


def test_r6_solution_endpoint_returns_real_solution(client, curriculum, db_factory):
    headers, data = _setup_ready(client, "解析独立")
    session_id = data["session"]["id"]
    lesson = _start_next(client, headers, session_id)  # lesson
    ack = client.post(
        f"/api/v1/tasks/{lesson['task']['id']}/acknowledge",
        json={"expected_version": lesson["task"]["version"]},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert ack.status_code == 200
    practice = _start_next(client, headers, session_id)
    exercise = practice["exercise"]
    qid = practice["question"]["id"]

    sol = client.post(
        f"/api/v1/exercises/{exercise['id']}/solution",
        json={"expected_version": exercise["version"]},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert sol.status_code == 200, sol.text
    body = sol.json()["data"]
    assert body["solution_seen"] is True
    assert body["solution"]

    db = db_factory()
    with db.begin():
        hints = db.get(Question, qid).private_hints
    assert body["solution"] not in hints  # 解析不是提示的复述

    # 公开视图永不含解析
    view = client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()["data"]
    assert "private_solution" not in json.dumps(view, ensure_ascii=False)


def test_r7_lesson_three_states_and_completion_rate(client, curriculum, db_factory):
    headers, data = _setup_ready(client, "三态讲解")
    session_id = data["session"]["id"]
    lesson = _start_next(client, headers, session_id)
    assert lesson["task"]["status"] == "active"

    session_db = db_factory()
    with session_db.begin():
        presented = session_db.execute(
            select(Event).where(Event.type == "lesson_presented")
        ).scalars().all()
        assert len(presented) == 1

    tasks = client.get(f"/api/v1/goals/{data['goal']['id']}/tasks", headers=headers).json()["data"]
    assert tasks["pending_minutes"] == 10  # 未确认前讲解仍占待办

    ack = client.post(
        f"/api/v1/tasks/{lesson['task']['id']}/acknowledge",
        json={"expected_version": lesson["task"]["version"]},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert ack.status_code == 200, ack.text
    assert ack.json()["data"]["task"]["status"] == "completed"

    tasks = client.get(f"/api/v1/goals/{data['goal']['id']}/tasks", headers=headers).json()["data"]
    assert tasks["pending_minutes"] == 5  # 只剩 practice

    with session_db.begin():
        acked = session_db.execute(
            select(Event).where(Event.type == "lesson_acknowledged")
        ).scalars().all()
        completed = session_db.execute(
            select(Event).where(Event.type == "task_completed")
        ).scalars().all()
        assert len(acked) == 1 and len(completed) == 1


def test_r7_acknowledge_rejects_practice_task(client, curriculum):
    headers, data = _setup_ready(client, "误确认练习")
    session_id = data["session"]["id"]
    lesson = _start_next(client, headers, session_id)
    client.post(
        f"/api/v1/tasks/{lesson['task']['id']}/acknowledge",
        json={"expected_version": lesson["task"]["version"]},
        headers={**headers, "Idempotency-Key": _key()},
    )
    practice = _start_next(client, headers, session_id)
    r = client.post(
        f"/api/v1/tasks/{practice['task']['id']}/acknowledge",
        json={"expected_version": practice["task"]["version"]},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert r.status_code == 400  # 练习任务不适用确认语义


def test_r8_finish_session_completes_for_real(client, curriculum, monkeypatch):
    headers, data = _setup_ready(client, "结束会话")
    session_id = data["session"]["id"]
    finish = json.dumps(
        {
            "action": "finish_session",
            "target_id": None,
            "reason_code": "student_request",
            "evidence_ids": [],
            "student_message": "今天到这里，进度已保存。",
        },
        ensure_ascii=False,
    )
    monkeypatch.setattr(
        coordinator_module, "build_gateway", lambda: LLMGateway(ScriptedProvider([finish]))
    )
    body = _message(client, headers, session_id)
    assert body["data"]["session_completed"] is True
    assert body["data"]["session_status"] == "completed"
    assert body["next_action"] == {"type": "show_result"}

    view = client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()["data"]
    assert view["session"]["status"] == "completed"
    assert view["resumable"] is None  # 已结束会话无恢复点

    blocked = _message(client, headers, session_id, expect=400)
    _ = blocked


def test_r8_completed_session_guards(client, curriculum, monkeypatch):
    """completed 会话：messages/start-next/pause/resume 一律 400。"""
    headers, data = _setup_ready(client, "结束守卫")
    session_id = data["session"]["id"]
    finish = json.dumps(
        {
            "action": "finish_session",
            "target_id": None,
            "reason_code": "student_request",
            "evidence_ids": [],
            "student_message": "结束。",
        },
        ensure_ascii=False,
    )
    monkeypatch.setattr(
        coordinator_module, "build_gateway", lambda: LLMGateway(ScriptedProvider([finish]))
    )
    _message(client, headers, session_id)

    for method, path, payload in (
        ("post", f"/api/v1/sessions/{session_id}/messages", {"text": "还在吗", "expected_version": _sv(client, headers, session_id)}),
        ("post", f"/api/v1/sessions/{session_id}/start-next", {"expected_version": _sv(client, headers, session_id)}),
        ("post", f"/api/v1/sessions/{session_id}/pause", {"expected_version": _sv(client, headers, session_id)}),
        ("post", f"/api/v1/sessions/{session_id}/resume", {"expected_version": _sv(client, headers, session_id)}),
    ):
        r = client.request(method, path, json=payload, headers={**headers, "Idempotency-Key": _key()})
        assert r.status_code == 400, (path, r.text)
        assert r.json()["error"]["code"] == "illegal_state"
