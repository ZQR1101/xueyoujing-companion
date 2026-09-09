"""T13-B Agentic RAG 测试。

验收（规划书）：≥10 个固定查询（知识点匹配/命中率）、排序可复现、引用完整性、
低于阈值 no_reliable_source、向量服务失败回退、检索故障回退课程包固定资源、
重排失败 rag_fallback、模型超时结构化错误、非法引用禁止展示、答案泄露过滤、
跨课程资源不可见；RAG 全链路不阻塞答题/评分/掌握度（服务不写业务状态表）。
"""

from __future__ import annotations

import json
from uuid import uuid4

from app.infrastructure.llm.gateway import LLMGateway, ScriptedProvider, TimeoutProvider
from app.infrastructure.rag_index import RagIndex, RagSegment
from app.services import tutoring_rag as rag_module


def _key() -> str:
    return f"t13b-{uuid4().hex}"


def _headers_of(client, name: str):
    r = client.post(
        "/api/v1/demo-identities", json={"display_name": name},
        headers={"Idempotency-Key": _key()},
    )
    return {"Authorization": f"Bearer {r.json()['data']['token']}"}


# 10 个固定查询：query → 期望命中的知识点（用于知识点匹配与命中率统计）
FIXED_QUERIES = [
    ("顶点式 括号 符号", "C04"),
    ("顶点坐标 代入 顶点式", "C04"),
    ("对称轴 怎么求", "C05"),
    ("开口方向 向上 向下", "C05"),
    ("图像 平移 上下平移", "C03"),
    ("二次函数 图像 基本性质", "C03"),
    ("平方 负数的平方 代入求值", "C01"),
    ("负数 平方 (-7)²", "C01"),
    ("函数 输入 输出 对应关系", "C02"),
    ("面积问题 逆向解方程 检验习惯", "C06"),
]


def _rag(client, headers, **payload):
    body = {"query": "顶点式", "content_type": "explanation", **payload}
    return client.post(
        "/api/v1/tutoring/rag", json=body, headers={**headers, "Idempotency-Key": _key()}
    )


def test_rag_does_not_enter_generation_inside_idempotency_transaction(client, curriculum, monkeypatch):
    """An online model call must not hold SQLite's write transaction open."""
    headers = _headers_of(client, "RAG 锁释放")
    original = rag_module.query_rag

    def probe(db, **kwargs):
        assert not db.in_transaction(), "RAG 生成前不应持有幂等写事务"
        return original(db, **kwargs)

    monkeypatch.setattr(rag_module, "query_rag", probe)
    response = _rag(client, headers, query="顶点式 括号 符号")
    assert response.status_code == 200, response.text


def test_fixed_queries_concept_match(client, curriculum):
    """10 个固定查询：来源知识点匹配与命中率（规划书要求记录）。"""
    hits = 0
    report: list[str] = []
    for query, expected_concept in FIXED_QUERIES:
        r = _rag(client, _headers_of(client, "固定查询"), query=query)
        assert r.status_code == 200, r.text
        sources = r.json()["data"]["sources"]
        top = sources[0] if sources else None
        ok = top is not None and top["concept_id"] == expected_concept
        hits += 1 if ok else 0
        report.append(f"{query} -> {top['source_id'] if top else '无'} (期望 {expected_concept}) {'✓' if ok else '✗'}")
    print("\n[RAG 命中报告]\n" + "\n".join(report))
    print(f"命中率: {hits}/{len(FIXED_QUERIES)}")
    assert hits >= 8, f"固定查询命中率过低：{hits}/{len(FIXED_QUERIES)}"


def test_rank_reproducible(client, curriculum):
    """固定索引、查询与过滤条件下，排序结果可复现。"""
    headers = _headers_of(client, "排序复现")
    r1 = _rag(client, headers, query="顶点式 括号 符号").json()["data"]
    r2 = _rag(client, headers, query="顶点式 括号 符号").json()["data"]
    assert [s["source_id"] for s in r1["sources"]] == [s["source_id"] for s in r2["sources"]]
    assert [s["retrieval_score"] for s in r1["sources"]] == [s["retrieval_score"] for s in r2["sources"]]
    assert r1["index_version"] == r2["index_version"]


def test_threshold_no_reliable_source(client, curriculum):
    """无关查询：低于可靠性阈值 → no_reliable_source，不编造内容。"""
    headers = _headers_of(client, "阈值")
    r = _rag(client, headers, query="量子纠缠 黑体辐射 超导")
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["status"] == "no_reliable_source"
    assert body["content"] is None
    assert body["safe_message"]
    assert body["fallback_reason"] == "below_reliability_threshold"


def test_vector_failure_falls_back_to_keyword(client, curriculum, monkeypatch):
    """向量服务失败 → 退回关键词检索，标记 vector_fallback，不阻塞。"""
    headers = _headers_of(client, "向量故障")
    index = get_index_with_broken_vector()
    monkeypatch.setattr(rag_module, "get_rag_index", lambda: index)
    r = _rag(client, headers, query="顶点式 括号 符号")
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["flags"].get("vector_fallback") is True
    assert body["sources"]
    assert body["status"] in ("ok", "rag_fallback")


def test_retrieval_failure_uses_fixed_resource(client, curriculum, monkeypatch):
    """关键词与向量均故障 → 课程包固定资源回退。"""
    headers = _headers_of(client, "检索全故障")

    class DeadIndex:
        course_id = "quadratic"
        index_version = "dead-index"

        def keyword_search(self, query, top_k=8):
            raise RuntimeError("keyword down")

        def vector_search(self, query, top_k=8):
            raise RuntimeError("vector down")

        def fixed_fallback(self, concept_id):
            seg = RagSegment(
                source_id="res-c04-seg01", resource_id="res-c04", course_id="quadratic",
                concept_id=concept_id or "C04", title="顶点式", heading="概念",
                content_type="explanation", text="顶点式 y = a(x - h)² + k 概念说明。",
            )
            return [(seg, 1.0)]

        def by_source(self, source_id, course_id):
            return None

    monkeypatch.setattr(rag_module, "get_rag_index", lambda: DeadIndex())
    r = _rag(client, headers, query="顶点式")
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["flags"].get("keyword_fallback") is True
    assert body["flags"].get("vector_fallback") is True
    assert body["flags"].get("retrieve_fallback") is True
    assert body["sources"] and body["sources"][0]["source_id"] == "res-c04-seg01"


def test_rerank_failure_keeps_initial_order(client, curriculum, monkeypatch):
    """重排失败 → 初始检索顺序 + rag_fallback 标记。"""
    headers = _headers_of(client, "重排故障")
    monkeypatch.setattr(rag_module, "_rerank", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("reranker down")))
    r = _rag(client, headers, query="顶点式 括号 符号")
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["flags"].get("rag_fallback") is True


def test_generator_timeout_returns_sources_not_block(client, curriculum, monkeypatch):
    """模型超时：结构化错误 + 仍返回可溯源来源，不阻塞（内容回退为资料摘要）。"""
    headers = _headers_of(client, "生成超时")
    monkeypatch.setattr(rag_module, "build_gateway", lambda: LLMGateway(TimeoutProvider()))
    r = _rag(client, headers, query="顶点式 括号 符号")
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["planner_source"] == "rule_fallback"
    assert "TimeoutException" in (body["fallback_reason"] or "")
    assert body["sources"]
    assert body["content"]  # 规则摘要（逐字摘录，非模型编造）


def test_citation_out_of_range_blocks_generated_content(client, curriculum, monkeypatch):
    """非法引用：引用校验失败 → 禁止展示生成内容，回退为可溯源摘要。"""
    headers = _headers_of(client, "非法引用")
    bad = json.dumps({"content": "这个结论来自 [99] 号资料，绝对可靠。"}, ensure_ascii=False)
    monkeypatch.setattr(
        rag_module, "build_gateway", lambda: LLMGateway(ScriptedProvider([bad, bad]))
    )
    r = _rag(client, headers, query="顶点式 括号 符号")
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert "来自 [99]" not in (body["content"] or "")
    assert body["planner_source"] == "rule_fallback"
    assert "citation_out_of_range" in (body["fallback_reason"] or "")
    assert body["sources"]


def test_hint_answer_leak_filtered_and_blocked(client, curriculum, db_factory, monkeypatch):
    """答案泄露：含标准答案的资料不进入提示结果；生成内容含答案被拦截。"""
    headers = _headers_of(client, "答案泄露")
    data = client.post(
        "/api/v1/goals",
        json={"course_id": "quadratic", "target_concept_ids": ["C01"], "daily_minutes": 30},
        headers={**headers, "Idempotency-Key": _key()},
    ).json()["data"]
    session_id = data["session"]["id"]

    def sv():
        return client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()["resource_version"]

    d = client.post(
        f"/api/v1/sessions/{session_id}/diagnosis",
        json={"expected_version": sv()}, headers={**headers, "Idempotency-Key": _key()},
    ).json()["data"]
    r_att = client.post(
        f"/api/v1/exercises/{d['exercise']['id']}/attempts",
        json={"answer": "B", "expected_version": d["exercise"]["version"]},
        headers={**headers, "Idempotency-Key": _key()},
    )
    assert r_att.status_code == 200
    cur = client.get(
        f"/api/v1/assessments/{d['assessment']['id']}", headers=headers
    ).json()["data"]["assessment"]["version"]
    client.post(
        f"/api/v1/assessments/{d['assessment']['id']}/complete",
        json={"expected_version": cur}, headers={**headers, "Idempotency-Key": _key()},
    )
    lesson = client.post(
        f"/api/v1/sessions/{session_id}/start-next",
        json={"expected_version": sv()}, headers={**headers, "Idempotency-Key": _key()},
    ).json()["data"]
    client.post(
        f"/api/v1/tasks/{lesson['task']['id']}/acknowledge",
        json={"expected_version": lesson["task"]["version"]},
        headers={**headers, "Idempotency-Key": _key()},
    )
    practice = client.post(
        f"/api/v1/sessions/{session_id}/start-next",
        json={"expected_version": sv()}, headers={**headers, "Idempotency-Key": _key()},
    ).json()["data"]
    ex_id = practice["exercise"]["id"]

    # 私有答案字符串从 DB 读取，构造一个"含答案"的假索引段验证过滤
    session_db = db_factory()
    with session_db.begin():
        from app.infrastructure.models import Question

        qid = session_db.query(Question).filter(Question.id == practice["question"]["id"]).first()
        answer_text = json.dumps(qid.private_answer, ensure_ascii=False)

    class LeakyIndex:
        course_id = "quadratic"
        index_version = "leaky"

        def __init__(self, answer: str):
            self.segs = [
                RagSegment(
                    source_id="leak-seg01", resource_id="res-c01", course_id="quadratic",
                    concept_id="C01", title="平方与代入", heading="提示",
                    content_type="hint", text=f"本题的正确答案是 {answer}，直接填它。",
                ),
                RagSegment(
                    source_id="safe-seg01", resource_id="res-c01", course_id="quadratic",
                    concept_id="C01", title="平方与代入", heading="符号陷阱",
                    content_type="hint", text="注意括号与负号的关系：先算平方再处理符号。",
                ),
            ]

        def keyword_search(self, query, top_k=8):
            return [(s, 0.8) for s in self.segs]

        def vector_search(self, query, top_k=8):
            return [(s, 0.5) for s in self.segs]

        def fixed_fallback(self, concept_id):
            return [(self.segs[1], 1.0)]

        def by_source(self, source_id, course_id):
            return next((s for s in self.segs if s.source_id == source_id), None)

    index = LeakyIndex(answer_text)
    monkeypatch.setattr(rag_module, "get_rag_index", lambda: index)
    r = _rag(client, headers, query="这题怎么做", content_type="hint", exercise_id=ex_id)
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    source_ids = [s["source_id"] for s in body["sources"]]
    assert "leak-seg01" not in source_ids, "含答案的资料必须被过滤"
    assert body["content"] and answer_text not in body["content"]


def test_source_endpoint_and_cross_course_invisible(client, curriculum):
    """来源查询接口：本课程可查；跨课程/不存在 → 404。"""
    headers = _headers_of(client, "来源查询")
    ok = client.get("/api/v1/tutoring/rag/sources/res-c04-seg01", headers=headers)
    assert ok.status_code == 200, ok.text
    assert ok.json()["data"]["concept_id"] == "C04"
    assert ok.json()["data"]["text"]

    missing = client.get("/api/v1/tutoring/rag/sources/res-physics-01", headers=headers)
    assert missing.status_code == 404


def test_trace_view_full(client, curriculum):
    """技术视图 trace：改写 query、过滤条件、候选、重排、最终来源、索引版本、耗时。"""
    headers = _headers_of(client, "trace视图")
    body = _rag(client, headers, query="顶点式 括号 符号").json()["data"]
    r = client.get(f"/api/v1/tutoring/rag/traces/{body['trace_id']}", headers=headers)
    assert r.status_code == 200, r.text
    t = r.json()["data"]
    assert t["raw_query"] == "顶点式 括号 符号"
    assert "顶点式" in t["rewritten_query"]
    assert t["filters"]["course_id"] == "quadratic"
    assert t["candidates"] and t["reranked"] and t["final_sources"]
    assert t["index_version"]
    assert "duration_ms" in t
    # 学生 B 不可见
    headers_b = _headers_of(client, "trace他人")
    assert client.get(f"/api/v1/tutoring/rag/traces/{body['trace_id']}", headers=headers_b).status_code == 404


def test_rag_never_touches_mastery(client, curriculum):
    """RAG 只提供教学内容：任意检索后掌握状态不变。"""
    headers = _headers_of(client, "掌握隔离")
    ov0 = client.get("/api/v1/me/overview", headers=headers).json()["data"]
    for query, _ in FIXED_QUERIES[:3]:
        assert _rag(client, headers, query=query).status_code == 200
    ov1 = client.get("/api/v1/me/overview", headers=headers).json()["data"]
    assert ov1["goals"] == ov0["goals"]


def get_index_with_broken_vector() -> RagIndex:
    """真实课程包索引 + 注入向量臂故障（保留关键词臂）。"""
    index = RagIndex()

    def broken(query, top_k=8):
        raise RuntimeError("embedding service down")

    index.vector_search = broken  # type: ignore[method-assign]
    return index
