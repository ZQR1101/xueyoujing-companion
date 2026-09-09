"""T06 辅导循环测试（A03 全链路、A10、A16、提示阶梯、暂停恢复）。"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select

from app.infrastructure.models import Task


def _key() -> str:
    return f"t06-{uuid4().hex}"


def _headers_of(client, name: str):
    r = client.post(
        "/api/v1/demo-identities", json={"display_name": name},
        headers={"Idempotency-Key": _key()},
    )
    return {"Authorization": f"Bearer {r.json()['data']['token']}"}


def _goal(client, headers, targets=None, daily=30):
    r = client.post(
        "/api/v1/goals",
        json={"course_id": "quadratic", "target_concept_ids": targets or [], "daily_minutes": daily},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _diagnose_correct(client, headers, session_id):
    version = client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()["resource_version"]
    r = client.post(
        f"/api/v1/sessions/{session_id}/diagnosis",
        json={"expected_version": version}, headers={**headers, "Idempotency-Key": _key()},
    )
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    # 诊断只考 1 题（单概念目标）；F1/F5 均为 screening，答 B 即可
    answers = {"Q-C01-F1": "B", "Q-C01-F5": "B", "Q-C01-F2": "1/4"}
    a = client.post(
        f"/api/v1/exercises/{d['exercise']['id']}/attempts",
        json={"answer": answers[d["question"]["id"]], "expected_version": d["exercise"]["version"]},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert a.status_code == 200, a.text
    current = client.get(
        f"/api/v1/assessments/{d['assessment']['id']}", headers=headers
    ).json()["data"]["assessment"]["version"]
    c = client.post(
        f"/api/v1/assessments/{d['assessment']['id']}/complete",
        json={"expected_version": current}, headers={**headers, "Idempotency-Key": _key()},
    )
    assert c.status_code == 200, c.text
    return c.json()["data"]


def _session_version(client, headers, session_id):
    return client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()["resource_version"]


def _start_next(client, headers, session_id, expect=200):
    version = _session_version(client, headers, session_id)
    r = client.post(
        f"/api/v1/sessions/{session_id}/start-next",
        json={"expected_version": version}, headers={**headers, "Idempotency-Key": _key()},
    )
    assert r.status_code == expect, r.text
    return r.json()["data"]


def _attempt(client, headers, exercise_id, answer, version, expect=200):
    r = client.post(
        f"/api/v1/exercises/{exercise_id}/attempts",
        json={"answer": answer, "expected_version": version},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert r.status_code == expect, r.text
    return r.json()


def _hint(client, headers, exercise_id, version, expect=200):
    r = client.post(
        f"/api/v1/exercises/{exercise_id}/hints",
        json={"expected_version": version}, headers={**headers, "Idempotency-Key": _key()},
    )
    assert r.status_code == expect, r.text
    return r.json()


def _setup_ready(client, name):
    headers = _headers_of(client, name)
    data = _goal(client, headers, targets=["C01"])
    _diagnose_correct(client, headers, data["session"]["id"])
    return headers, data


def test_full_learning_loop_hint_transfer_task_complete(client, curriculum, db_factory):
    headers, data = _setup_ready(client, "全流程")
    session_id = data["session"]["id"]

    lesson = _start_next(client, headers, session_id)
    assert lesson["task"]["type"] == "lesson"
    assert lesson["content"]["excerpt"], "讲解内容应有摘录"
    # 合同 v1.2 R7：呈现≠完成，讲解任务等待学生确认
    assert lesson["task"]["status"] == "active"
    tasks_now = client.get(f"/api/v1/goals/{data['goal']['id']}/tasks", headers=headers).json()["data"]
    lesson_task = next(t for t in tasks_now["tasks"] if t["type"] == "lesson")
    assert lesson_task["status"] == "active"

    ack_version = lesson["task"]["version"]
    ack = client.post(
        f"/api/v1/tasks/{lesson['task']['id']}/acknowledge",
        json={"expected_version": ack_version},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert ack.status_code == 200, ack.text
    assert ack.json()["data"]["task"]["status"] == "completed"

    practice = _start_next(client, headers, session_id)
    assert practice["task"]["type"] == "practice"
    # 练习任务抽题：practice/screening 优先、按 id 升序，F1 已用 → Q-C01-F5
    assert practice["question"]["id"] == "Q-C01-F5"
    exercise = practice["exercise"]

    # 首答错误：练习保持 open，邀请重试
    wrong = _attempt(client, headers, exercise["id"], "A", exercise["version"])
    assert wrong["data"]["attempt"]["grade"] == "incorrect"
    assert wrong["data"]["evidence"]["eligible"] is True  # 错误也是有效证据
    assert wrong["data"]["mastery_delta"]["after"]["estimate"] == 0.5  # [1,0]
    assert wrong["next_action"] == {"type": "retry_exercise", "target_id": exercise["id"]}

    # 提示递进：每次只升一级（注意练习版本随提示递增）
    h1 = _hint(client, headers, exercise["id"], exercise["version"])
    assert h1["data"]["level"] == 1
    h2 = _hint(client, headers, exercise["id"], h1["data"]["exercise_version"])
    assert h2["data"]["level"] == 2

    # 原题重试答对：提示过 → 不产生独立证据；安排迁移新题
    retry = _attempt(client, headers, exercise["id"], "B", h2["data"]["exercise_version"])
    assert retry["data"]["attempt"]["grade"] == "correct"
    assert retry["data"]["evidence"]["eligible"] is False
    assert retry["data"]["evidence"]["exclusion_reason"] == "not_first_attempt"
    assert retry["data"]["mastery_delta"]["after"]["estimate"] == 0.5  # 未加证据
    assert retry["next_action"]["type"] == "next_question"
    assert retry["data"]["transfer_available"] is True

    # 迁移题：attempts 服务 transfer 用途优先 → Q-C01-F3（新题族）独立答对 → 新证据
    transfer_version = _session_version(client, headers, session_id)
    got = client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()["data"]["resumable"]
    assert got["question"]["id"] == "Q-C01-F3"  # transfer 用途、新题族
    transfer = _attempt(client, headers, got["exercise"]["id"], "25", got["exercise"]["version"])
    assert transfer["data"]["evidence"]["eligible"] is True
    assert transfer["data"]["mastery_delta"]["after"]["estimate"] == 0.6  # [1,0,1] → 3/5
    assert transfer["next_action"] is None  # 迁移完成 → 任务结束

    tasks_now = client.get(f"/api/v1/goals/{data['goal']['id']}/tasks", headers=headers).json()["data"]
    practice_task = next(t for t in tasks_now["tasks"] if t["type"] == "practice")
    assert practice_task["status"] == "completed"


def _ack_lesson(client, headers, lesson_task):
    r = client.post(
        f"/api/v1/tasks/{lesson_task['id']}/acknowledge",
        json={"expected_version": lesson_task["version"]},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


def test_a16_solution_marks_assisted_and_arranges_new_question(client, curriculum):
    headers, data = _setup_ready(client, "看解析")
    session_id = data["session"]["id"]
    lesson = _start_next(client, headers, session_id)  # lesson
    _ack_lesson(client, headers, lesson["task"])
    practice = _start_next(client, headers, session_id)
    exercise = practice["exercise"]

    sol = client.post(
        f"/api/v1/exercises/{exercise['id']}/solution",
        json={"expected_version": exercise["version"]},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert sol.status_code == 200, sol.text
    body = sol.json()["data"]
    assert body["solution_seen"] is True
    assert body["answer"]  # 明确请求解析才返回完整答案
    assert body["solution"]  # 合同 v1.2 R6：独立完整解析

    attempt = _attempt(client, headers, exercise["id"], "B", body["exercise_version"])
    assert attempt["data"]["attempt"]["grade"] == "correct"
    assert attempt["data"]["evidence"]["exclusion_reason"] == "solution_seen"
    assert attempt["next_action"]["type"] == "next_question"  # 安排新题验证
    new_q = client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()["data"]["resumable"]
    assert new_q["question"]["id"] == "Q-C01-F3"  # transfer 用途优先、新题族


def test_a10_hint_level_restored_after_restart(client, curriculum):
    headers, data = _setup_ready(client, "恢复检查")
    session_id = data["session"]["id"]
    lesson = _start_next(client, headers, session_id)
    _ack_lesson(client, headers, lesson["task"])
    practice = _start_next(client, headers, session_id)
    exercise = practice["exercise"]

    wrong = _attempt(client, headers, exercise["id"], "A", exercise["version"])
    _ = wrong
    h1 = _hint(client, headers, exercise["id"], exercise["version"])
    current_version = h1["data"]["exercise_version"]

    # 模拟关闭应用后重新进入：仅用读接口
    view = client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()["data"]
    assert view["resumable"]["kind"] == "learning"
    assert view["resumable"]["exercise"]["hint_level"] == 1
    assert view["resumable"]["question"]["id"] == "Q-C01-F5"

    # 暂停 → 恢复 → 同一题、提示等级保持
    version = _session_version(client, headers, session_id)
    p = client.post(
        f"/api/v1/sessions/{session_id}/pause",
        json={"expected_version": version}, headers={**headers, "Idempotency-Key": _key()},
    )
    assert p.status_code == 200, p.text
    assert p.json()["data"]["session"]["status"] == "paused"

    # A10 语义：暂停 + 打开练习 → 直接回到原处作答（恢复不强制走 resume 端点）
    answered = _attempt(client, headers, exercise["id"], "B", current_version)
    assert answered["data"]["attempt"]["grade"] == "correct"
    assert answered["data"]["evidence"]["eligible"] is False  # 带提示重做不计证据
    # 答对后系统已安排迁移题（新练习），恢复应回到迁移题
    transfer_id = answered["next_action"]["target_id"]

    version = _session_version(client, headers, session_id)
    r = client.post(
        f"/api/v1/sessions/{session_id}/resume",
        json={"expected_version": version}, headers={**headers, "Idempotency-Key": _key()},
    )
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["session"]["status"] == "learning"
    assert body["resume_location"]["exercise"]["id"] == transfer_id
    assert body["resume_location"]["exercise"]["hint_level"] == 0  # 迁移题是新题，无提示


def test_hint_ladder_caps_at_four(client, curriculum):
    headers, data = _setup_ready(client, "提示到顶")
    session_id = data["session"]["id"]
    lesson = _start_next(client, headers, session_id)
    _ack_lesson(client, headers, lesson["task"])
    practice = _start_next(client, headers, session_id)
    exercise = practice["exercise"]
    _attempt(client, headers, exercise["id"], "A", exercise["version"])

    current = exercise["version"]
    for expected_level in (1, 2, 3, 4):
        body = _hint(client, headers, exercise["id"], current)
        assert body["data"]["level"] == expected_level
        current = body["data"]["exercise_version"]
    _hint(client, headers, exercise["id"], current, expect=400)


def test_start_next_recovers_open_exercise_first(client, curriculum):
    headers, data = _setup_ready(client, "恢复优先")
    session_id = data["session"]["id"]
    lesson = _start_next(client, headers, session_id)
    _ack_lesson(client, headers, lesson["task"])
    practice = _start_next(client, headers, session_id)
    exercise = practice["exercise"]
    _attempt(client, headers, exercise["id"], "A", exercise["version"])  # 保持 open

    again = _start_next(client, headers, session_id)
    assert again["resumed"] is True
    assert again["exercise"]["id"] == exercise["id"]
