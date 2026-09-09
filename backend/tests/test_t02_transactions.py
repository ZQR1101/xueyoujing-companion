"""T02 数据与事务验收测试。

覆盖：迁移与重启恢复、幂等（同键同载荷/异载荷）、两学生隔离（仓库级）、
未知字段拒绝、目标创建校验与事件写入。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, func

from app.domain.errors import ResourceNotFound
from app.infrastructure.models import Event, Goal, IdempotencyRecord, Student
from app.infrastructure.repositories import goals as goals_repo


def test_healthz_open(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_demo_identity_and_auth(client, make_identity, auth_headers):
    data = make_identity("小明")
    assert data["token"]
    assert data["student"]["display_name"] == "小明"
    assert data["student"]["daily_minutes"] == 30

    bad = client.get("/healthz", headers=auth_headers("not-a-token"))
    assert bad.status_code == 200

    no_auth = client.post(
        "/api/v1/goals",
        json={"course_id": "quadratic", "daily_minutes": 30},
    )
    assert no_auth.status_code == 401
    assert no_auth.json()["error"]["code"] == "invalid_token"


def test_idempotent_demo_identity(client):
    key = "same-key-1"
    first = client.post(
        "/api/v1/demo-identities",
        json={"display_name": "小红"},
        headers={"Idempotency-Key": key},
    )
    second = client.post(
        "/api/v1/demo-identities",
        json={"display_name": "小红"},
        headers={"Idempotency-Key": key},
    )
    assert first.status_code == 200 and second.status_code == 200
    assert (
        first.json()["data"]["student"]["id"]
        == second.json()["data"]["student"]["id"]
    )
    assert first.json()["data"]["token"] == second.json()["data"]["token"]


def test_idempotent_conflict_on_different_payload(client):
    key = "conflict-key-1"
    first = client.post(
        "/api/v1/demo-identities",
        json={"display_name": "小红"},
        headers={"Idempotency-Key": key},
    )
    second = client.post(
        "/api/v1/demo-identities",
        json={"display_name": "小刚"},
        headers={"Idempotency-Key": key},
    )
    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "idempotency_conflict"


def test_missing_idempotency_key(client, make_identity, auth_headers):
    token = make_identity("小明")["token"]
    response = client.post(
        "/api/v1/goals",
        json={"course_id": "quadratic", "daily_minutes": 30},
        headers=auth_headers(token),
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "missing_idempotency_key"


def test_goal_creation_version_and_event(client, make_identity, auth_headers, seed_concepts):
    seed_concepts()
    token = make_identity("小明")["token"]
    response = client.post(
        "/api/v1/goals",
        json={
            "course_id": "quadratic",
            "target_concept_ids": ["C01", "C02"],
            "daily_minutes": 20,
        },
        headers={**auth_headers(token), "Idempotency-Key": "goal-1"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["resource_version"] == 1
    assert body["data"]["goal"]["status"] == "active"
    assert body["data"]["session"]["status"] == "ready"

    replay = client.post(
        "/api/v1/goals",
        json={
            "course_id": "quadratic",
            "target_concept_ids": ["C01", "C02"],
            "daily_minutes": 20,
        },
        headers={**auth_headers(token), "Idempotency-Key": "goal-1"},
    )
    assert replay.json()["data"]["goal"]["id"] == body["data"]["goal"]["id"]


def test_goal_writes_event_once(client, make_identity, auth_headers, seed_concepts, db_factory):
    seed_concepts()
    token = make_identity("小明")["token"]
    client.post(
        "/api/v1/goals",
        json={"course_id": "quadratic", "daily_minutes": 25},
        headers={**auth_headers(token), "Idempotency-Key": "goal-event-1"},
    )
    # 幂等重放不得重复写事件（A08）
    client.post(
        "/api/v1/goals",
        json={"course_id": "quadratic", "daily_minutes": 25},
        headers={**auth_headers(token), "Idempotency-Key": "goal-event-1"},
    )
    session = db_factory()
    with session.begin():
        events = session.execute(
            select(Event).where(Event.type == "goal_created")
        ).scalars().all()
        assert len(events) == 1


def test_restart_recovery(engine, db_factory):
    session = db_factory()
    with session.begin():
        student = Student(display_name="持久化", daily_minutes=30, token_hash="hash-x")
        session.add(student)
    reopened = db_factory()
    with reopened.begin():
        found = reopened.execute(
            select(Student).where(Student.display_name == "持久化")
        ).scalar_one()
        assert found.token_hash == "hash-x"
        count = reopened.execute(select(func.count()).select_from(Goal)).scalar()
        assert count == 0


def test_two_students_isolated_at_repository(
    client, make_identity, auth_headers, seed_concepts, db_factory
):
    seed_concepts()
    token_a = make_identity("甲")["token"]
    token_b = make_identity("乙")["token"]
    response = client.post(
        "/api/v1/goals",
        json={"course_id": "quadratic", "daily_minutes": 30},
        headers={**auth_headers(token_a), "Idempotency-Key": "goal-a"},
    )
    goal_id = response.json()["data"]["goal"]["id"]

    session = db_factory()
    with session.begin():
        student_b = session.execute(
            select(Student).where(Student.display_name == "乙")
        ).scalar_one()
        with pytest.raises(ResourceNotFound):
            goals_repo.goal_owned(session, student_b.id, goal_id)
        # 甲本人可读
        student_a = session.execute(
            select(Student).where(Student.display_name == "甲")
        ).scalar_one()
        assert goals_repo.goal_owned(session, student_a.id, goal_id).id == goal_id
        _ = token_b


def test_unknown_fields_rejected(client):
    response = client.post(
        "/api/v1/demo-identities",
        json={"display_name": "小明", "student_id": "forged"},
        headers={"Idempotency-Key": "k-unknown"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_goal_validation_errors(client, make_identity, auth_headers, seed_concepts):
    seed_concepts()
    token = make_identity("小明")["token"]
    headers = {**auth_headers(token), "Idempotency-Key": "g-inv"}

    unknown_course = client.post(
        "/api/v1/goals",
        json={"course_id": "nope", "daily_minutes": 30},
        headers=headers,
    )
    assert unknown_course.status_code == 400
    assert unknown_course.json()["error"]["code"] == "illegal_state"

    unknown_concept = client.post(
        "/api/v1/goals",
        json={"course_id": "quadratic", "target_concept_ids": ["C99"], "daily_minutes": 30},
        headers=headers,
    )
    assert unknown_concept.status_code == 400

    out_of_range = client.post(
        "/api/v1/goals",
        json={"course_id": "quadratic", "daily_minutes": 121},
        headers=headers,
    )
    assert out_of_range.status_code == 422
    assert out_of_range.json()["error"]["code"] == "invalid_request"


def test_idempotency_record_stored(client, db_factory):
    client.post(
        "/api/v1/demo-identities",
        json={"display_name": "小红"},
        headers={"Idempotency-Key": "stored-1"},
    )
    session = db_factory()
    with session.begin():
        records = session.execute(select(IdempotencyRecord)).scalars().all()
        assert len(records) == 1
        assert records[0].path == "/api/v1/demo-identities"
        assert records[0].response_status == 200
