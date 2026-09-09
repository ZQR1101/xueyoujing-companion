"""T05～T07 真实环境冒烟：诊断→任务→辅导循环→Agent 决策→恢复。

用法（需后端已启动）：
    cd backend
    uv run python ../scripts/smoke_t07.py
"""

import json
import sys
import urllib.request
import uuid

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8000/api/v1"
RUN = uuid.uuid4().hex[:8]


def call(method, path, payload=None, token=None, key=None):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if key:
        req.add_header("Idempotency-Key", f"{key}-{RUN}")
    data = json.dumps(payload).encode() if payload is not None else None
    with urllib.request.urlopen(req, data) as resp:
        return json.loads(resp.read())


def main() -> None:
    identity = call("POST", "/demo-identities", {"display_name": "冒烟五七"}, key="id")
    token = identity["data"]["token"]
    print("1 身份:", identity["data"]["student"]["id"])

    goal = call("POST", "/goals", {"course_id": "quadratic", "target_concept_ids": ["C01", "C02"], "daily_minutes": 25}, token, key="goal")
    session_id = goal["data"]["session"]["id"]
    goal_id = goal["data"]["goal"]["id"]
    print("2 目标:", goal_id, "daily=25")

    def sv():
        return call("GET", f"/sessions/{session_id}", token=token)["resource_version"]

    version = sv()
    diag = call("POST", f"/sessions/{session_id}/diagnosis", {"expected_version": version}, token, key="diag")
    d = diag["data"]
    answers = {"Q-C01-F1": "B", "Q-C01-F5": "B", "Q-C01-F2": "1/4", "Q-C02-F1": "A"}
    a = call("POST", f"/exercises/{d['exercise']['id']}/attempts", {"answer": answers[d['question']['id']], "expected_version": d['exercise']['version']}, token, key="att1")
    cur = call("GET", f"/assessments/{d['assessment']['id']}", token=token)["data"]["assessment"]["version"]
    complete = call("POST", f"/assessments/{d['assessment']['id']}/complete", {"expected_version": cur}, token, key="done")
    print("3 诊断完成: 计划 v", complete["data"]["plan"]["version"], complete["data"]["plan"]["policy_version"], complete["data"]["plan"]["ordered_concept_ids"])

    path = call("GET", f"/goals/{goal_id}/path", token=token)["data"]
    print("4 路径:", {n["concept_id"]: n["status"] for n in path["nodes"]})

    lesson = call("POST", f"/sessions/{session_id}/start-next", {"expected_version": sv()}, token, key="sn1")
    print("5 讲解呈现:", lesson["data"]["task"]["type"], lesson["data"]["task"]["status"], "| 摘录:", (lesson["data"]["content"]["excerpt"] or "")[:40], "…")
    ack = call("POST", f"/tasks/{lesson['data']['task']['id']}/acknowledge", {"expected_version": lesson["data"]["task"]["version"]}, token, key="ack")
    print("   讲解确认 →", ack["data"]["task"]["status"])

    practice = call("POST", f"/sessions/{session_id}/start-next", {"expected_version": sv()}, token, key="sn2")
    ex, q = practice["data"]["exercise"], practice["data"]["question"]
    print("6 练习题:", q["id"])

    # 练习任务抽到 Q-C01-F5（screening 选择题）：错答 A，重试 B
    wrong = call("POST", f"/exercises/{ex['id']}/attempts", {"answer": "A", "expected_version": ex["version"]}, token, key="attw")
    print("7 错答: grade=", wrong["data"]["attempt"]["grade"], "next=", wrong["next_action"]["type"], "after=", wrong["data"]["mastery_delta"]["after"]["estimate"])

    h1 = call("POST", f"/exercises/{ex['id']}/hints", {"expected_version": wrong["data"]["versions"]["exercise"]}, token, key="h1")
    h2 = call("POST", f"/exercises/{ex['id']}/hints", {"expected_version": h1["data"]["exercise_version"]}, token, key="h2")
    print("8 提示递进:", h1["data"]["level"], h2["data"]["level"], "|", h2["data"]["hint"][:24], "…")

    retry = call("POST", f"/exercises/{ex['id']}/attempts", {"answer": "B", "expected_version": h2["data"]["exercise_version"]}, token, key="attr")
    print("9 原题重试对: evidence=", retry["data"]["evidence"], "next=", retry["next_action"]["type"])

    sid = retry["next_action"]["target_id"]
    sv_transfer = call("GET", f"/sessions/{session_id}", token=token)["data"]["resumable"]["exercise"]["version"]
    transfer = call("POST", f"/exercises/{sid}/attempts", {"answer": "25", "expected_version": sv_transfer}, token, key="attt")
    print("10 迁移新题对: eligible=", transfer["data"]["evidence"]["eligible"], "after=", transfer["data"]["mastery_delta"]["after"]["estimate"])

    pause = call("POST", f"/sessions/{session_id}/pause", {"expected_version": sv()}, token, key="pause")
    resume = call("POST", f"/sessions/{session_id}/resume", {"expected_version": sv()}, token, key="resume")
    print("13 暂停/恢复:", pause["data"]["session"]["status"], "→", resume["data"]["session"]["status"])

    msg = call("POST", f"/sessions/{session_id}/messages", {"text": "接下来做什么？", "expected_version": sv()}, token, key="msg")
    print("11 Agent:", msg["data"]["decision"]["action"], "| source=", msg["data"]["decision"]["planner_source"], "model=", msg["data"]["decision"]["model_id"], "| 回复:", msg["data"]["reply"][:30])
    print("11b 会话状态:", msg["data"]["session_status"], "| 已结束:", msg["data"]["session_completed"])
    if msg["data"]["session_completed"]:
        import urllib.error

        try:
            call("POST", f"/sessions/{session_id}/pause", {"expected_version": sv()}, token, key="pause-done")
            print("12b 已结束会话仍可暂停：异常！")
            raise SystemExit(1)
        except urllib.error.HTTPError as e:
            print("12b 已结束会话 pause 被拒:", e.code, "(符合预期)")
        try:
            _message_blocked = call("POST", f"/sessions/{session_id}/messages", {"text": "还在吗？", "expected_version": sv()}, token, key="msg-done")
            print("12c 已结束会话仍可发消息：异常！")
            raise SystemExit(1)
        except urllib.error.HTTPError as e:
            print("12c 已结束会话 messages 被拒:", e.code, "(符合预期)")

    decisions = call("GET", f"/sessions/{session_id}/decisions", token=token)["data"]["decisions"]
    print("12 决策轨迹:", len(decisions), "条；最近:", decisions[-1]["action"], decisions[-1]["planner_source"])

    reflection = call("POST", f"/sessions/{session_id}/reflection", {"text": "学到了负数的平方。", "expected_version": sv()}, token, key="ref")
    print("14 小结: 掌握", reflection["data"]["summary"]["mastered_concept_ids"], "证据", reflection["data"]["summary"]["evidence_count_total"])

    print("SMOKE 5-7 OK")


if __name__ == "__main__":
    main()
