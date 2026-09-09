"""T02~T04 真实环境冒烟：身份→目标→诊断→作答→完成→概览。

用法（需后端已启动）：
    cd backend
    uv run python ../scripts/smoke_t04.py
"""

import json
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8000/api/v1"


def call(method, path, payload=None, token=None, key=None):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if key:
        req.add_header("Idempotency-Key", key)
    data = json.dumps(payload).encode() if payload is not None else None
    with urllib.request.urlopen(req, data) as resp:
        return json.loads(resp.read())


def main() -> None:
    identity = call("POST", "/demo-identities", {"display_name": "冒烟学生"}, key="smoke-identity-1")
    token = identity["data"]["token"]
    print("1 身份:", identity["data"]["student"]["id"])

    goal_body = call("POST", "/goals", {"course_id": "quadratic", "target_concept_ids": ["C01"], "daily_minutes": 25}, token, key="smoke-goal-1")
    session = goal_body["data"]["session"]
    print("2 目标+会话:", goal_body["data"]["goal"]["id"], "session:", session["id"], "v", session["version"])

    diag = call("POST", f"/sessions/{session['id']}/diagnosis", {"expected_version": session["version"]}, token, key="smoke-diag-1")
    assessment = diag["data"]["assessment"]
    exercise = diag["data"]["exercise"]
    question = diag["data"]["question"]
    print("3 诊断:", assessment["id"], "题目:", question["id"], question["prompt"][:30])
    assert "private_answer" not in question and "private_hints" not in question

    attempt = call("POST", f"/exercises/{exercise['id']}/attempts", {"answer": "B", "expected_version": exercise["version"]}, token, key="smoke-attempt-1")
    print("4 作答:", attempt["data"]["attempt"]["grade"], "| after:", attempt["data"]["mastery_delta"]["after"], "| versions:", attempt["data"]["versions"])
    print("   next:", attempt["next_action"])

    replay = call("POST", f"/exercises/{exercise['id']}/attempts", {"answer": "B", "expected_version": exercise["version"]}, token, key="smoke-attempt-1")
    print("4b 幂等重放: attempt 一致 =", replay["data"]["attempt"]["id"] == attempt["data"]["attempt"]["id"])

    assessment_now = call("GET", f"/assessments/{assessment['id']}", token=token)
    version = assessment_now["data"]["assessment"]["version"]
    complete = call("POST", f"/assessments/{assessment['id']}/complete", {"expected_version": version}, token, key="smoke-complete-1")
    print("5 完成: coverage:", complete["data"]["coverage"], "| plan:", complete["data"]["plan"]["ordered_concept_ids"], complete["data"]["plan"]["policy_version"])

    overview = call("GET", "/me/overview", token=token)
    goal_entry = overview["data"]["goals"][0]
    mastery_c01 = [m for m in goal_entry["mastery"] if m["concept_id"] == "C01"][0]
    print("6 概览: 覆盖率", goal_entry["coverage"], "| C01:", mastery_c01["status"], mastery_c01["estimate"])

    history = call("GET", "/me/mastery-history?concept_id=C01", token=token)
    print("7 历史: formula", history["data"]["formula_version"], "points", len(history["data"]["points"]))

    print("SMOKE OK")


if __name__ == "__main__":
    main()
