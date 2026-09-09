"""T14-B reflection, evidence, versioning, ownership, and fallback tests."""
from __future__ import annotations

import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.infrastructure.llm.gateway import LLMGateway, ScriptedProvider, TimeoutProvider
from app.infrastructure.models import (
    Attempt, Evidence, Event, Exercise, Goal, LearningReflection,
    LearningSession, MemoryFact, Question, Student, Task,
)
from app.services import memory as memory_service
from app.services import reflection as reflection_service


def _key() -> str:
    return f"t14b-{uuid4().hex}"


def _identity(client, name: str) -> tuple[dict, dict]:
    response = client.post(
        "/api/v1/demo-identities",
        json={"display_name": name},
        headers={"Idempotency-Key": _key()},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    return data, {"Authorization": f"Bearer {data['token']}"}


def _setup_ready(client, name: str) -> tuple[dict, dict, dict]:
    identity, headers = _identity(client, name)
    response = client.post(
        "/api/v1/goals",
        json={"course_id": "quadratic", "target_concept_ids": ["C01"], "daily_minutes": 30},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    session_id = data["session"]["id"]
    version = client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()["resource_version"]
    diagnosis = client.post(
        f"/api/v1/sessions/{session_id}/diagnosis",
        json={"expected_version": version},
        headers={**headers, "Idempotency-Key": _key()},
    ).json()["data"]
    answer = "B" if diagnosis["question"]["type"] == "mcq" else "1/4"
    attempt = client.post(
        f"/api/v1/exercises/{diagnosis['exercise']['id']}/attempts",
        json={"answer": answer, "expected_version": diagnosis["exercise"]["version"]},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert attempt.status_code == 200, attempt.text
    assessment = client.get(
        f"/api/v1/assessments/{diagnosis['assessment']['id']}", headers=headers
    ).json()["data"]["assessment"]
    completed = client.post(
        f"/api/v1/assessments/{assessment['id']}/complete",
        json={"expected_version": assessment["version"]},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert completed.status_code == 200, completed.text
    return identity, headers, data


def _post(client, headers: dict, session_id: str, *, idem: str | None = None, **payload):
    return client.post(
        f"/api/v1/sessions/{session_id}/reflection",
        json=payload,
        headers={**headers, "Idempotency-Key": idem or _key()},
    )


def test_summary_metrics_use_real_session_evidence(client, curriculum):
    _identity_data, headers, data = _setup_ready(client, "小结指标")
    session_id = data["session"]["id"]

    response = client.get(f"/api/v1/sessions/{session_id}/summary-metrics", headers=headers)
    assert response.status_code == 200, response.text
    metrics = response.json()["data"]
    assert metrics["independent_answer_count"] >= 1
    assert metrics["new_eligible_evidence_count"] == metrics["independent_answer_count"]
    assert metrics["completed_task_count"] >= 0
    assert metrics["study_seconds"] >= 0


def _seed_answer(
    db_factory, *, student_name: str, session_id: str, purpose: str,
    concept_id: str, hint_level: int = 0, solution_seen: bool = False, eligible: bool = False,
) -> tuple[str, str]:
    db = db_factory()
    with db.begin():
        student = db.execute(select(Student).where(Student.display_name == student_name)).scalars().one()
        learning_session = db.get(LearningSession, session_id)
        question = db.execute(
            select(Question).where(
                Question.purpose == purpose,
                Question.primary_concept_id == concept_id,
            )
        ).scalars().first()
        assert question is not None
        task = Task(
            student_id=student.id, goal_id=learning_session.goal_id,
            concept_id=question.primary_concept_id, type="practice", status="active",
            estimated_minutes=5,
        )
        db.add(task)
        db.flush()
        exercise = Exercise(
            student_id=student.id, task_id=task.id, question_id=question.id,
            hint_level=hint_level, solution_seen=solution_seen,
        )
        db.add(exercise)
        db.flush()
        attempt = Attempt(
            student_id=student.id, exercise_id=exercise.id, answer="seed", grade="correct",
            hint_level_at_submission=hint_level,
        )
        db.add(attempt)
        db.flush()
        event = Event(
            student_id=student.id, session_id=session_id, type="answer_graded",
            payload={"attempt_id": attempt.id, "exercise_id": exercise.id, "question_id": question.id},
        )
        db.add(event)
        db.flush()
        db.add(Evidence(
            student_id=student.id, concept_id=question.primary_concept_id,
            attempt_id=attempt.id, family_id=question.family_id, score=1,
            eligible=eligible,
            exclusion_reason=None if eligible else ("solution_seen" if solution_seen else "hint_used"),
            event_id=event.id,
        ))
        return question.primary_concept_id, event.id


def test_normal_generation_recovery_and_planner_context(client, curriculum, db_factory):
    _identity_data, headers, data = _setup_ready(client, "正常生成")
    session_id = data["session"]["id"]
    response = _post(client, headers, session_id, text="我还想用新题确认。")
    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["planner_source"] == "llm"
    assert body["learned"] and body["learned"][0]["evidence_event_ids"]
    assert body["memory_write_status"] == "ok"
    assert client.get(f"/api/v1/sessions/{session_id}/reflection", headers=headers).json()["data"]["reflection_id"] == body["reflection_id"]
    assert client.get(f"/api/v1/sessions/{session_id}/next-recommendation", headers=headers).status_code == 200
    overview = client.get(f"/api/v1/sessions/{session_id}/reflection-overview", headers=headers).json()["data"]
    assert any(x["type"] == "reflection_fact" for x in overview["active_memories"])

    db = db_factory()
    with db.begin():
        student = db.execute(select(Student).where(Student.display_name == "正常生成")).scalars().one()
        learning_session = db.get(LearningSession, session_id)
        goal = db.get(Goal, learning_session.goal_id)
        context = memory_service.build_context(
            db, student_id=student.id, session=learning_session, goal=goal, task=None
        )
        assert any(x["id"] in {m["memory_id"] for m in overview["active_memories"]} for x in context["memory_facts"])
        assert all(x["evidence_event_ids"] for x in context["memory_facts"])
        event_ids = body["learned"][0]["evidence_event_ids"]
        events = db.execute(select(Event).where(Event.id.in_(event_ids))).scalars().all()
        assert len(events) == len(event_ids)
        assert all(e.student_id == student.id and e.session_id == session_id for e in events)


def test_hint_solution_and_transfer_classification(client, curriculum, db_factory):
    _identity_data, headers, data = _setup_ready(client, "证据分类")
    session_id = data["session"]["id"]
    hinted_concept, hinted_event = _seed_answer(
        db_factory, student_name="证据分类", session_id=session_id,
        purpose="practice", concept_id="C02", hint_level=1,
    )
    solved_concept, solved_event = _seed_answer(
        db_factory, student_name="证据分类", session_id=session_id,
        purpose="screening", concept_id="C03", solution_seen=True,
    )
    transfer_concept, transfer_event = _seed_answer(
        db_factory, student_name="证据分类", session_id=session_id,
        purpose="transfer", concept_id="C04", eligible=True,
    )
    body = _post(client, headers, session_id).json()["data"]
    learned = {x["concept_id"]: x for x in body["learned"]}
    uncertain = {x["concept_id"]: x for x in body["still_uncertain"]}
    assert transfer_event in learned[transfer_concept]["evidence_event_ids"]
    assert hinted_concept not in learned
    assert hinted_event in uncertain[hinted_concept]["evidence_event_ids"]
    assert solved_concept not in learned
    assert solved_event in uncertain[solved_concept]["evidence_event_ids"]


@pytest.mark.parametrize(
    ("provider", "reason_fragment"),
    [
        (ScriptedProvider(["not-json", "still-not-json"]), "invalid_json"),
        (TimeoutProvider(), "timeout"),
    ],
)
def test_invalid_json_and_timeout_fallback(client, curriculum, monkeypatch, provider, reason_fragment):
    _identity_data, headers, data = _setup_ready(client, f"回退-{reason_fragment}")
    monkeypatch.setattr(reflection_service, "build_gateway", lambda: LLMGateway(provider))
    body = _post(client, headers, data["session"]["id"]).json()["data"]
    assert body["planner_source"] == "reflection_rule_fallback"
    assert reason_fragment in body["fallback_reason"].lower()
    assert body["learned"][0]["evidence_event_ids"]


@pytest.mark.parametrize("bad_ids", [[], ["fabricated-event-id"]])
def test_missing_or_fake_model_evidence_is_rejected(client, curriculum, monkeypatch, bad_ids):
    _identity_data, headers, data = _setup_ready(client, f"伪证据-{len(bad_ids)}")
    output = json.dumps({
        "learned": [{
            "concept_id": "C01", "statement": "存在独立首答正确证据。",
            "evidence_event_ids": bad_ids,
        }],
        "still_uncertain": [], "evidence_summary": {}, "learning_characteristics": [],
    }, ensure_ascii=False)
    monkeypatch.setattr(
        reflection_service, "build_gateway",
        lambda: LLMGateway(ScriptedProvider([output], stay_on_last=True)),
    )
    body = _post(client, headers, data["session"]["id"]).json()["data"]
    assert body["planner_source"] == "reflection_rule_fallback"
    assert body["fallback_reason"] in {
        "reflection_fact_missing_evidence_event_id", "reflection_unknown_evidence_event_id"
    }
    assert body["learned"][0]["evidence_event_ids"]


def test_superseded_dispute_restore_idempotency_and_cross_student(client, curriculum):
    _identity_data, headers, data = _setup_ready(client, "版本链")
    session_id = data["session"]["id"]
    idem = _key()
    first = _post(client, headers, session_id, idem=idem).json()["data"]
    repeated = _post(client, headers, session_id, idem=idem).json()["data"]
    assert first["reflection_id"] == repeated["reflection_id"]
    _post(client, headers, session_id)
    memories = client.get("/api/v1/courses/quadratic/memories", headers=headers).json()["data"]["memories"]
    current = next(x for x in memories if x["type"] == "reflection_fact")
    chain = client.get(f"/api/v1/memories/{current['memory_id']}/chain", headers=headers).json()["data"]["chain"]
    assert [x["version"] for x in chain[:2]] == [2, 1]
    assert chain[1]["status"] == "superseded"

    disputed = client.post(
        f"/api/v1/memories/{current['memory_id']}/correction",
        json={"status": "disputed"}, headers={**headers, "Idempotency-Key": _key()},
    )
    assert disputed.json()["data"]["status"] == "disputed"
    active = client.get("/api/v1/courses/quadratic/memories", headers=headers).json()["data"]["memories"]
    assert current["memory_id"] not in {x["memory_id"] for x in active}
    restored = client.post(
        f"/api/v1/memories/{current['memory_id']}/restore",
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert restored.json()["data"]["status"] == "active"

    _other_identity, other_headers = _identity(client, "其他学生")
    assert client.get(f"/api/v1/sessions/{session_id}/reflection", headers=other_headers).status_code == 404
    assert client.get(f"/api/v1/memories/{current['memory_id']}/chain", headers=other_headers).status_code == 404
    assert client.get("/api/v1/courses/quadratic/memories", headers=other_headers).status_code == 404


def test_memory_failure_does_not_block_reflection(client, curriculum, monkeypatch):
    _identity_data, headers, data = _setup_ready(client, "记忆失败")
    monkeypatch.setattr(reflection_service, "_write_memories", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("write failed")))
    response = _post(client, headers, data["session"]["id"])
    assert response.status_code == 200, response.text
    assert response.json()["data"]["memory_write_status"] == "failed:RuntimeError"
    assert client.get(f"/api/v1/sessions/{data['session']['id']}/reflection", headers=headers).status_code == 200


def test_recommendation_failure_returns_current_plan(client, curriculum, monkeypatch):
    _identity_data, headers, data = _setup_ready(client, "推荐失败")
    monkeypatch.setattr(reflection_service, "_recommendation", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("recommend failed")))
    body = _post(client, headers, data["session"]["id"]).json()["data"]
    assert body["next_recommendation"]["status"] == "plan_fallback"
    assert body["next_recommendation"]["plan_version"] is not None
    assert body["next_recommendation"]["items"]


def test_forced_rule_fallback_marker(client, curriculum):
    _identity_data, headers, data = _setup_ready(client, "规则回退")
    body = _post(client, headers, data["session"]["id"], force_llm_failure=True).json()["data"]
    assert body["planner_source"] == "reflection_rule_fallback"
    assert body["fallback_reason"] == "forced_llm_failure"


def test_competition_demo_closed_loop_and_refresh_recovery(client, curriculum, db_factory):
    """诊断→规划→错误→提示→RAG→迁移→反思→记忆→重规划→刷新恢复。"""
    _identity_data, headers, data = _setup_ready(client, "赛事闭环")
    session_id = data["session"]["id"]
    goal_id = data["goal"]["id"]

    path_before = client.get(f"/api/v1/goals/{goal_id}/path", headers=headers)
    assert path_before.status_code == 200 and path_before.json()["data"]["plan"]

    version = client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()["resource_version"]
    lesson = client.post(
        f"/api/v1/sessions/{session_id}/start-next",
        json={"expected_version": version}, headers={**headers, "Idempotency-Key": _key()},
    ).json()["data"]
    assert lesson["task"]["type"] == "lesson" and lesson["content"]["excerpt"]
    ack = client.post(
        f"/api/v1/tasks/{lesson['task']['id']}/acknowledge",
        json={"expected_version": lesson["task"]["version"]},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert ack.status_code == 200

    version = client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()["resource_version"]
    practice = client.post(
        f"/api/v1/sessions/{session_id}/start-next",
        json={"expected_version": version}, headers={**headers, "Idempotency-Key": _key()},
    ).json()["data"]
    exercise = practice["exercise"]
    wrong = client.post(
        f"/api/v1/exercises/{exercise['id']}/attempts",
        json={"answer": "A", "expected_version": exercise["version"]},
        headers={**headers, "Idempotency-Key": _key()},
    ).json()
    assert wrong["data"]["attempt"]["grade"] == "incorrect"
    hint = client.post(
        f"/api/v1/exercises/{exercise['id']}/hints",
        json={"expected_version": exercise["version"]},
        headers={**headers, "Idempotency-Key": _key()},
    ).json()["data"]
    assert hint["level"] == 1

    rag = client.post(
        "/api/v1/tutoring/rag",
        json={
            "query": "平方代入这一步为什么这样算？", "content_type": "hint",
            "concept_id": "C01", "exercise_id": exercise["id"],
            "allowed_concept_ids": ["C01"],
        },
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert rag.status_code == 200, rag.text
    assert rag.json()["data"]["sources"]

    retried = client.post(
        f"/api/v1/exercises/{exercise['id']}/attempts",
        json={"answer": "B", "expected_version": hint["exercise_version"]},
        headers={**headers, "Idempotency-Key": _key()},
    ).json()
    assert retried["data"]["evidence"]["eligible"] is False
    resumable = client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()["data"]["resumable"]
    assert resumable["question"]["purpose"] == "transfer"
    transfer = client.post(
        f"/api/v1/exercises/{resumable['exercise']['id']}/attempts",
        json={"answer": "25", "expected_version": resumable["exercise"]["version"]},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert transfer.status_code == 200, transfer.text
    assert transfer.json()["data"]["evidence"]["eligible"] is True

    reflection = _post(client, headers, session_id, text="提示后我理解了，迁移题可以独立完成。")
    assert reflection.status_code == 200
    reflection_data = reflection.json()["data"]
    assert reflection_data["learned"] and reflection_data["memory_write_status"] == "ok"
    assert reflection_data["evidence_summary"]["hint_level_counts"]
    assert reflection_data["evidence_summary"]["rag_usage"]

    path = client.get(f"/api/v1/goals/{goal_id}/path", headers=headers).json()
    replanned = client.post(
        f"/api/v1/goals/{goal_id}/replan",
        json={"reason": "reflection_updated", "expected_version": path["resource_version"]},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert replanned.status_code == 200, replanned.text
    # 模拟页面刷新/进程新请求：结果由 SQLite 恢复，不依赖前端内存。
    recovered = client.get(f"/api/v1/sessions/{session_id}/reflection-overview", headers=headers)
    assert recovered.status_code == 200
    assert recovered.json()["data"]["reflection_id"] == reflection_data["reflection_id"]
    assert recovered.json()["data"]["active_memories"]

    second_goal_response = client.post(
        "/api/v1/goals",
        json={"course_id": "quadratic", "target_concept_ids": ["C01"], "daily_minutes": 20},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert second_goal_response.status_code == 200, second_goal_response.text
    second_data = second_goal_response.json()["data"]
    db = db_factory()
    with db.begin():
        student = db.execute(select(Student).where(Student.display_name == "赛事闭环")).scalars().one()
        second_session = db.get(LearningSession, second_data["session"]["id"])
        second_goal = db.get(Goal, second_data["goal"]["id"])
        next_context = memory_service.build_context(
            db, student_id=student.id, session=second_session, goal=second_goal, task=None
        )
        prior_memory_ids = {m["memory_id"] for m in recovered.json()["data"]["active_memories"]}
        assert any(fact["id"] in prior_memory_ids for fact in next_context["memory_facts"])
