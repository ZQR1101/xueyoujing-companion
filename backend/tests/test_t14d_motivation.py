"""T14-D motivation projection: 25 real rules, rewards and isolation."""
from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select

from app.infrastructure.models import Event, Goal, Student, Task
from app.services.motivation import BADGE_DEFS


def _key() -> str:
    return f"t14d-{uuid4().hex}"


def _identity(client, name: str) -> tuple[dict, dict]:
    response = client.post(
        "/api/v1/demo-identities", json={"display_name": name},
        headers={"Idempotency-Key": _key()},
    )
    data = response.json()["data"]
    return data, {"Authorization": f"Bearer {data['token']}"}


def test_badge_catalog_has_25_evidence_backed_rules(client, curriculum, db_factory):
    _identity_data, headers = _identity(client, "徽章规则")
    response = client.get("/api/v1/me/motivation", headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["badge_total"] == 25 == len(BADGE_DEFS)
    assert len(data["badge_catalog"]) == 25
    assert len({badge["id"] for badge in data["badge_catalog"]}) == 25
    assert all(set(badge["progress"]) == {"current", "target"} for badge in data["badge_catalog"])
    assert all(badge["progress"]["current"] <= badge["progress"]["target"] for badge in data["badge_catalog"])
    assert all(not badge["evidence_event_ids"] for badge in data["badge_catalog"] if not badge["acquired"])


def test_task_badge_reward_claim_and_student_isolation(client, curriculum, db_factory):
    _identity_data, headers = _identity(client, "奖励学生")
    other_identity, other_headers = _identity(client, "空白学生")
    goal_response = client.post(
        "/api/v1/goals",
        json={"course_id": "quadratic", "target_concept_ids": ["C01"], "daily_minutes": 30},
        headers={**headers, "Idempotency-Key": _key()},
    )
    goal_id = goal_response.json()["data"]["goal"]["id"]
    db = db_factory()
    with db.begin():
        student = db.execute(select(Student).where(Student.display_name == "奖励学生")).scalars().one()
        for index in range(3):
            task = Task(
                student_id=student.id, goal_id=goal_id, concept_id="C01",
                type="practice", status="completed", estimated_minutes=5,
            )
            db.add(task)
            db.flush()
            db.add(Event(
                student_id=student.id, type="task_completed",
                payload={"task_id": task.id, "concept_id": "C01", "type": "practice", "index": index},
            ))

    mine = client.get("/api/v1/me/motivation", headers=headers).json()["data"]
    task_badge = next(b for b in mine["badge_catalog"] if b["id"] == "task_runner")
    assert task_badge["acquired"] is True
    assert task_badge["progress"] == {"current": 3, "target": 3}
    assert len(task_badge["evidence_event_ids"]) == 3
    reward = next(r for r in mine["rewards"] if r["reward_id"] == "task_first")
    claimed = client.post(
        f"/api/v1/me/motivation/rewards/{reward['reward_id']}/claim",
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert claimed.status_code == 200 and claimed.json()["data"]["claimed"] is True
    assert not any(r["reward_id"] == "task_first" for r in client.get("/api/v1/me/motivation", headers=headers).json()["data"]["rewards"])

    other = client.get("/api/v1/me/motivation", headers=other_headers).json()["data"]
    assert other["points"] == 0 and other["earned_badge_count"] == 0
    board = client.get("/api/v1/motivation/leaderboard", headers=other_headers).json()["data"]["entries"]
    assert board[0]["points"] >= 15
    assert all(row["display_name"].startswith("学习者") for row in board)
