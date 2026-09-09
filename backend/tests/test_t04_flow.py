"""T04 诊断与掌握集成测试（规格书 §17 验收用例）。"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select

from app.infrastructure.models import (
    Assessment,
    Attempt,
    Evidence,
    Exercise,
    MasteryState,
    Plan,
    Question,
)
from app.infrastructure.repositories import learning as learning_repo

# 屏幕题标准答案：round1 各概念 screening 题依次为
# C01=B, C02=A, C03=B, C04=A, C05=B, C06=A
SCREENING_ANSWERS = {
    "Q-C01-F1": "B",
    "Q-C02-F1": "A",
    "Q-C03-F1": "B",
    "Q-C04-F1": "A",
    "Q-C05-F1": "B",
    "Q-C06-F1": "A",
}
NUMERIC_ANSWERS = {
    "Q-C01-F2": "1/4",
    "Q-C01-F3": "25",
    "Q-C01-F4": "B",
    "Q-C02-F2": "9",
    "Q-C02-F3": "B",
    "Q-C02-F4": "4.25",
}
# 抽题稳定排序：screening 优先、按 id 升序（X 系列排在 F1-F8 之后）。
# C01 的抽取序列前几轮为 F1 → F5 → X01(screening) → F2 → F3 → ...
C01_SEQUENCE_ANSWERS = {
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


def _key() -> str:
    return f"test-{uuid4().hex}"


def _create_goal(client, headers, targets=None, daily_minutes=30) -> dict:
    response = client.post(
        "/api/v1/goals",
        json={
            "course_id": "quadratic",
            "target_concept_ids": targets or [],
            "daily_minutes": daily_minutes,
        },
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _start_diagnosis(client, headers, session_id, version, expect=200) -> dict:
    response = client.post(
        f"/api/v1/sessions/{session_id}/diagnosis",
        json={"expected_version": version},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert response.status_code == expect, response.text
    return response.json()


def _answer(client, headers, exercise_id, answer, version, expect=200) -> dict:
    response = client.post(
        f"/api/v1/exercises/{exercise_id}/attempts",
        json={"answer": answer, "expected_version": version},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert response.status_code == expect, response.text
    return response.json()


def _complete(client, headers, assessment_id, expect=200) -> dict:
    # 完成前现取评估版本（每次作答都会升版本）
    current = client.get(
        f"/api/v1/assessments/{assessment_id}", headers=headers
    ).json()["data"]["assessment"]["version"]
    response = client.post(
        f"/api/v1/assessments/{assessment_id}/complete",
        json={"expected_version": current},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert response.status_code == expect, response.text
    return response.json()


def _run_round(client, headers, session_id, version, answer_for) -> tuple[dict, dict, dict]:
    body = _start_diagnosis(client, headers, session_id, version)
    data = body["data"]
    assessment = data["assessment"]
    exercise = data["exercise"]
    current_question = data["question"]
    attempts_body = None
    while exercise is not None:
        answer = answer_for(current_question)
        attempts_body = _answer(
            client, headers, exercise["id"], answer, exercise["version"]
        )
        next_action = attempts_body["next_action"]
        if next_action and next_action["type"] == "next_question":
            # 通过 GET 拿下一题（A15 校验点）
            got = client.get(
                f"/api/v1/assessments/{assessment['id']}", headers=headers
            )
            assert got.status_code == 200
            nxt = got.json()["data"]["next"]
            if nxt is None:
                exercise = None
                current_question = None
            else:
                exercise = nxt["exercise"]
                current_question = nxt["question"]
        else:
            exercise = None
    return body, attempts_body, assessment


def test_a01_new_student_unassessed(client, make_identity, auth_headers, curriculum):
    token = make_identity("新生")["token"]
    headers = auth_headers(token)
    data = _create_goal(client, headers)
    overview = client.get("/api/v1/me/overview", headers=headers).json()["data"]
    goal = overview["goals"][0]
    assert goal["coverage"] == {"assessed_count": 0, "total_count": 6, "ratio": 0.0}
    assert all(m["status"] == "unassessed" and m["estimate"] is None for m in goal["mastery"])


def test_full_diagnosis_round_and_overview(client, make_identity, auth_headers, curriculum):
    token = make_identity("小明")["token"]
    headers = auth_headers(token)
    data = _create_goal(client, headers)
    session = data["session"]

    start = _start_diagnosis(client, headers, session["id"], session["version"])
    assessment = start["data"]["assessment"]
    assert len(assessment["question_ids"]) == 6
    # A15：诊断响应里的题目不含私有字段
    assert "private_answer" not in start["data"]["question"]
    assert "private_hints" not in start["data"]["question"]

    # 逐题作答（全部答对）
    exercise = start["data"]["exercise"]
    current_question = start["data"]["question"]
    grades = []
    while exercise is not None:
        answer = SCREENING_ANSWERS[current_question["id"]]
        body = _answer(client, headers, exercise["id"], answer, exercise["version"])
        grades.append(body["data"]["attempt"]["grade"])
        next_action = body["next_action"]
        if next_action["type"] == "next_question":
            got = client.get(
                f"/api/v1/assessments/{assessment['id']}", headers=headers
            ).json()["data"]["next"]
            if got is None:
                exercise = None
            else:
                exercise = got["exercise"]
                current_question = got["question"]
        else:
            assert next_action["type"] == "complete_assessment"
            exercise = None
    assert grades == ["correct"] * 6

    complete = _complete(client, headers, assessment["id"])
    payload = complete["data"]
    assert payload["coverage"]["assessed"] == ["C01", "C02", "C03", "C04", "C05", "C06"]
    assert payload["uncovered_concept_ids"] == []
    assert all(entry["status"] == "developing" for entry in payload["snapshot"])
    assert payload["plan"]["ordered_concept_ids"] == ["C01", "C02", "C03", "C04", "C05", "C06"]
    assert payload["plan"]["version"] == 1

    overview = client.get("/api/v1/me/overview", headers=headers).json()["data"]
    goal = overview["goals"][0]
    assert goal["coverage"]["assessed_count"] == 6
    assert all(m["estimate"] == 2 / 3 for m in goal["mastery"])
    assert len(overview["recent_evidence"]) == 6


def test_a02_three_families_correct_masters(client, make_identity, auth_headers, curriculum):
    token = make_identity(" mastered ")["token"]
    token = make_identity("求掌握")["token"]
    headers = auth_headers(token)
    data = _create_goal(client, headers, targets=["C01"])
    session = data["session"]
    version = session["version"]

    # 前三轮依次抽到 Q-C01-F1、F5、X01
    answers = {k: C01_SEQUENCE_ANSWERS[k] for k in ("Q-C01-F1", "Q-C01-F5", "Q-C01-X01")}
    estimates = []
    for _ in range(3):
        body, last, assessment = _run_round(
            client, headers, session["id"], version,
            lambda q: answers[q["id"]],
        )
        estimates.append(last["data"]["mastery_delta"]["after"])
        version = last["resource_version"] + 0  # exercise version
        got = client.get(f"/api/v1/sessions/{session['id']}", headers=headers)
        version = got.json()["resource_version"]
        _complete(client, headers, assessment["id"])
        got = client.get(f"/api/v1/sessions/{session['id']}", headers=headers)
        version = got.json()["resource_version"]

    assert estimates[0] == {"estimate": 2 / 3, "status": "developing"}
    assert estimates[1] == {"estimate": 0.75, "status": "developing"}
    assert estimates[2]["estimate"] == 0.8
    assert estimates[2]["status"] == "mastered"


def test_a03_two_wrong_gives_needs_support(client, make_identity, auth_headers, curriculum):
    token = make_identity("错两题")["token"]
    headers = auth_headers(token)
    data = _create_goal(client, headers, targets=["C01"])
    session = data["session"]

    # 前两轮依次抽到 Q-C01-F1、F5，全部答错
    wrong_answers = {"Q-C01-F1": "A", "Q-C01-F5": "A"}
    version = session["version"]
    for _ in range(2):
        body, last, assessment = _run_round(
            client, headers, session["id"], version,
            lambda q: wrong_answers[q["id"]],
        )
        version = last["resource_version"]
        got = client.get(f"/api/v1/sessions/{session['id']}", headers=headers)
        version = got.json()["resource_version"]
        _complete(client, headers, assessment["id"])
        got = client.get(f"/api/v1/sessions/{session['id']}", headers=headers)
        version = got.json()["resource_version"]

    assert last["data"]["mastery_delta"]["after"] == {"estimate": 0.25, "status": "needs_support"}


def test_hint_used_attempt_not_eligible(
    client, make_identity, auth_headers, curriculum, db_factory
):
    token = make_identity("要提示")["token"]
    headers = auth_headers(token)
    data = _create_goal(client, headers, targets=["C01"])
    session = data["session"]
    start = _start_diagnosis(client, headers, session["id"], session["version"])
    exercise = start["data"]["exercise"]

    # 模拟提示已展示（T06 才有 hints 端点）：直接把 hint_level 置 1
    session_db = db_factory()
    with session_db.begin():
        row = session_db.get(Exercise, exercise["id"])
        row.hint_level = 1

    body = _answer(client, headers, exercise["id"], "B", exercise["version"])
    assert body["data"]["evidence"]["eligible"] is False
    assert body["data"]["evidence"]["exclusion_reason"] == "hint_used"
    # 掌握度保持 unassessed（提示后作答不加分）
    assert body["data"]["mastery_delta"]["after"]["estimate"] is None
    assert body["data"]["mastery_delta"]["after"]["status"] == "unassessed"


def test_a08_idempotent_attempt_no_double_evidence(
    client, make_identity, auth_headers, curriculum, db_factory
):
    token = make_identity("重发")["token"]
    headers = auth_headers(token)
    data = _create_goal(client, headers, targets=["C01"])
    session = data["session"]
    start = _start_diagnosis(client, headers, session["id"], session["version"])
    exercise = start["data"]["exercise"]

    key = "same-attempt-key"
    payload = {"answer": "B", "expected_version": exercise["version"]}
    first = client.post(
        f"/api/v1/exercises/{exercise['id']}/attempts",
        json=payload,
        headers={**headers, "Idempotency-Key": key},
    )
    second = client.post(
        f"/api/v1/exercises/{exercise['id']}/attempts",
        json=payload,
        headers={**headers, "Idempotency-Key": key},
    )
    assert first.status_code == 200 and second.status_code == 200
    assert (
        first.json()["data"]["attempt"]["id"]
        == second.json()["data"]["attempt"]["id"]
    )

    session_db = db_factory()
    with session_db.begin():
        attempts = session_db.execute(select(Attempt)).scalars().all()
        evidences = session_db.execute(select(Evidence)).scalars().all()
        assert len(attempts) == 1
        assert len(evidences) == 1


def test_a09_concurrent_writes_one_409(client, make_identity, auth_headers, curriculum):
    token = make_identity("双开")["token"]
    headers = auth_headers(token)
    data = _create_goal(client, headers, targets=["C01"])
    session = data["session"]
    start = _start_diagnosis(client, headers, session["id"], session["version"])
    exercise = start["data"]["exercise"]

    import threading

    results = []
    lock = threading.Lock()

    def submit(answer: str) -> None:
        local = auth_headers(token)
        response = client.post(
            f"/api/v1/exercises/{exercise['id']}/attempts",
            json={"answer": answer, "expected_version": exercise["version"]},
            headers={**local, "Idempotency-Key": _key()},
        )
        with lock:
            results.append(response.status_code)

    threads = [
        threading.Thread(target=submit, args=("B",)),
        threading.Thread(target=submit, args=("A",)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(results) == [200, 409]


def test_a09b_stale_version_after_close(client, make_identity, auth_headers, curriculum):
    token = make_identity("过期")["token"]
    headers = auth_headers(token)
    data = _create_goal(client, headers, targets=["C01"])
    session = data["session"]
    start = _start_diagnosis(client, headers, session["id"], session["version"])
    exercise = start["data"]["exercise"]

    _answer(client, headers, exercise["id"], "B", exercise["version"])
    stale = client.post(
        f"/api/v1/exercises/{exercise['id']}/attempts",
        json={"answer": "A", "expected_version": exercise["version"]},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "version_conflict"


def test_a11_cross_student_access_denied(client, make_identity, auth_headers, curriculum):
    token_a = make_identity("甲")["token"]
    token_b = make_identity("乙")["token"]
    headers_a = auth_headers(token_a)
    headers_b = auth_headers(token_b)

    data = _create_goal(client, headers_a, targets=["C01"])
    session_id = data["session"]["id"]
    start = _start_diagnosis(client, headers_a, session_id, data["session"]["version"])
    assessment_id = start["data"]["assessment"]["id"]
    exercise_id = start["data"]["exercise"]["id"]

    assert client.get(f"/api/v1/sessions/{session_id}", headers=headers_b).status_code == 404
    assert client.get(f"/api/v1/assessments/{assessment_id}", headers=headers_b).status_code == 404
    forged = client.post(
        f"/api/v1/exercises/{exercise_id}/attempts",
        json={"answer": "B", "expected_version": 1},
        headers={**headers_b, "Idempotency-Key": _key()},
    )
    assert forged.status_code == 404


def test_a14_insufficient_items_when_pool_exhausted(
    client, make_identity, auth_headers, curriculum, db_factory
):
    token = make_identity("刷完")["token"]
    headers = auth_headers(token)
    data = _create_goal(client, headers, targets=["C01"])
    session = data["session"]

    # 从数据库读出 C01 全部题目的标准答案，逐轮答对直到题池耗尽
    session_db = db_factory()
    with session_db.begin():
        c01_questions = session_db.execute(
            select(Question).where(Question.primary_concept_id == "C01")
        ).scalars().all()
        answers = {q.id: str(q.private_answer["value"]) for q in c01_questions}
    total = len(answers)
    assert total >= 8

    version = session["version"]
    for _ in range(total):
        body, last, assessment = _run_round(
            client, headers, session["id"], version,
            lambda q: answers[q["id"]],
        )
        version = last["resource_version"]
        got = client.get(f"/api/v1/sessions/{session['id']}", headers=headers)
        version = got.json()["resource_version"]
        _complete(client, headers, assessment["id"])
        got = client.get(f"/api/v1/sessions/{session['id']}", headers=headers)
        version = got.json()["resource_version"]

    exhausted = _start_diagnosis(
        client, headers, session["id"], version, expect=400
    )
    assert exhausted["error"]["code"] == "insufficient_items"


def test_skip_is_read_only_and_moves_on(
    client, make_identity, auth_headers, curriculum, db_factory
):
    token = make_identity("跳题")["token"]
    headers = auth_headers(token)
    data = _create_goal(client, headers, targets=["C01", "C02"])
    session = data["session"]
    start = _start_diagnosis(client, headers, session["id"], session["version"])
    assessment = start["data"]["assessment"]
    first_exercise = start["data"]["exercise"]

    skipped = client.get(
        f"/api/v1/assessments/{assessment['id']}",
        params={"after_exercise_id": first_exercise["id"]},
        headers=headers,
    ).json()["data"]["next"]
    assert skipped is not None
    assert skipped["exercise"]["id"] != first_exercise["id"]

    session_db = db_factory()
    with session_db.begin():
        assert len(session_db.execute(select(Attempt)).scalars().all()) == 0


def test_mastery_history_endpoint(client, make_identity, auth_headers, curriculum):
    token = make_identity("历史")["token"]
    headers = auth_headers(token)
    data = _create_goal(client, headers, targets=["C01"])
    session = data["session"]
    body, last, assessment = _run_round(
        client, headers, session["id"], session["version"], lambda q: "B"
    )
    _complete(client, headers, assessment["id"])

    history = client.get(
        "/api/v1/me/mastery-history", params={"concept_id": "C01"}, headers=headers
    ).json()["data"]
    assert history["concept_id"] == "C01"
    assert len(history["points"]) == 1
    point = history["points"][0]
    assert point["before"]["estimate"] is None
    assert point["after"]["estimate"] == 2 / 3
    assert history["formula_version"] == "v1"


def test_review_due_set_on_mastered(client, make_identity, auth_headers, curriculum, db_factory):
    token = make_identity("到期")["token"]
    headers = auth_headers(token)
    data = _create_goal(client, headers, targets=["C01"])
    session = data["session"]

    answers = {k: C01_SEQUENCE_ANSWERS[k] for k in ("Q-C01-F1", "Q-C01-F5", "Q-C01-X01")}
    version = session["version"]
    for _ in range(3):
        body, last, assessment = _run_round(
            client, headers, session["id"], version, lambda q: answers[q["id"]]
        )
        version = last["resource_version"]
        got = client.get(f"/api/v1/sessions/{session['id']}", headers=headers)
        version = got.json()["resource_version"]
        _complete(client, headers, assessment["id"])
        got = client.get(f"/api/v1/sessions/{session['id']}", headers=headers)
        version = got.json()["resource_version"]

    session_db = db_factory()
    with session_db.begin():
        state = session_db.execute(
            select(MasteryState).where(MasteryState.concept_id == "C01")
        ).scalar_one()
        assert state.status == "mastered"
        assert state.review_due_at is not None
