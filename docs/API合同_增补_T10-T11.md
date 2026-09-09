# API 合同增补（T10-B / T11-B / T12-B 新增端点）

基础：docs/API合同_v1.2.md 不变；本文件按规划书 T10/T11/T12 新增端点，供 T10-F/T11-F/T12-F 联调。
统一前缀 `/api/v1`，信封与错误格式同 v1.2（`data / next_action / resource_version / trace_id`；
私有资源归属当前演示令牌学生；写请求带 `Idempotency-Key`）。

## T10-B：AI 学情诊断

### POST /goals/{goal_id}/diagnosis-report

- 请求：`{}`（空体，预留扩展）+ `Idempotency-Key`。
- 行为：读取学习状态；有效证据 < 2 时不调用模型，直接返回可解释规则结果
  （`status=insufficient_evidence, planner_source=rule_fallback, fallback_reason=insufficient_evidence`）；
  否则调用 LLM 生成结构化诊断，Schema/归属校验失败修复一次，仍失败或超时回退规则结果并标记。
- 返回 `data`：

```json
{
  "report_id": "uuid",
  "status": "ok | insufficient_evidence",
  "planner_source": "llm | rule_fallback",
  "model_id": "deepseek-v4-flash | mock | null",
  "fallback_reason": null,
  "summary": "一句话核心结论",
  "observations":  [{"concept_id": "C01|null", "title": "…", "detail": "…"}],
  "hypotheses":    [{"concept_id": "C01|null", "title": "…", "detail": "…"}],
  "recommended_probe": {"concept_id": "C01|null", "summary": "…", "reason": "…"},
  "evidence_ids": ["…"],
  "state": {"evidence_total": 2, "eligible_total": 2,
            "coverage": {"assessed_count": 2, "total_count": 6},
            "mastery": [{"concept_id": "C01", "title": "平方与代入", "status": "developing",
                          "estimate": 0.33, "evidence_count": 1}]},
  "policy_version": "t10b-v1",
  "duration_ms": 2468
}
```

- 约束：AI 诊断与确定性评分分开保存（只写 diagnosis_reports/llm_usage，不改掌握状态）；
  concept_id/evidence_id 经归属与课程存在性校验，虚构即回退；学生视图无模型原始输出。
- 错误：404 目标不存在或不属于当前学生；409/422/401 同 v1.2。

### GET /goals/{goal_id}/diagnosis-report

最近一次诊断（同上 data 外加 `created_at`）；尚未生成时 404 `resource_not_found`。只读零写入。

## T11-B：LLM 路径决策

### POST /goals/{goal_id}/path-decision

- 请求：`{"expected_version": <当前计划版本，0=尚无计划>}` + `Idempotency-Key`。
- 流程：规则生成候选（schedule_review → insert_probe → continue_task）→ LLM 在候选内选择 →
  action+target 精确匹配候选、evidence 归属校验（失败修复一次）→ 规则执行器执行合法行动 →
  持久化决策轨迹 → 仅任务集合真实变化时生成新 Plan.version。
- 返回 `data`：

```json
{
  "decision_id": "uuid",
  "status": "adjusted | unchanged | no_legal_action",
  "candidate_actions": [{"action": "insert_probe", "target_id": "C01",
                          "reason_code": "repeated_error", "label": "…", "message": "…"}],
  "selected_action": {"action": "insert_probe", "target_id": "C01", "reason_code": "repeated_error",
                       "reason": "模型/规则给出的安排原因", "label": "…"},
  "reason": "…",
  "evidence_ids": ["…"],
  "policy_version": "v1-rules",
  "model_id": "deepseek-v4-flash | mock | null",
  "planner_source": "llm | rule_fallback",
  "fallback_reason": null,
  "duration_ms": 1047,
  "plan_before": {"version": 1, "ordered_concept_ids": ["C01", "…"]},
  "plan_after":  {"version": 2, "ordered_concept_ids": ["C01", "…"]},
  "changed": true,
  "current_task": {"id": "…", "concept_id": "C01", "type": "practice", "status": "queued",
                    "estimated_minutes": 5, "version": 1},
  "input_state_hash": "sha256（相同输入/规则版本/候选集合的重放依据）"
}
```

- 失败语义：候选为空 → 200 `status=no_legal_action`（不伪造任务）；模型超时/非法 JSON/伪造引用 →
  200 规则首选行动 + `rule_fallback` 标记；expected_version 与当前计划不符 → 409 `version_conflict`
  （消息含当前版本号，客户端以 GET 取最新计划，不覆盖其他版本）。
- 错误：404 目标不属于当前学生；401/422 同 v1.2。

### GET /goals/{goal_id}/path-decision

最近一次决策（同上 data 外加 `current_plan_version`）；尚未生成 404。只读零写入。

### GET /goals/{goal_id}/path-decisions

决策轨迹列表（最新在前，默认 20 条），`{"decisions": [ … 同上结构 ]}`。查询接口，零写入。

## T12-B：Tutor Agent 启发式辅导

### POST /exercises/{exercise_id}/thinking

- 请求：`{"text": "学生的思路/困惑（1~1000 字）"}` + `Idempotency-Key`。
- 行为：LLM 结构化分析（温和反馈 / 可能的问题 / 苏格拉底式追问），Schema 校验失败修复一次，
  仍失败或超时回退规则文案并标记；只写 events（thinking_submitted / tutor_feedback）+ llm_usage，
  不产生/不修改任何掌握证据；题目已关闭返回 400 illegal_state。
- 返回 `data`：

```json
{
  "exercise_id": "…",
  "feedback": "一句温和反馈",
  "possible_problem": "可能的问题（一句）",
  "socratic_question": "一个引导学生自己推进的追问",
  "planner_source": "llm | rule_fallback",
  "model_id": "deepseek-v4-flash | null",
  "fallback_reason": null,
  "hint_level": 1,
  "duration_ms": 6120
}
```

### GET /exercises/{exercise_id}/tutoring-trace

作答与辅导轨迹时间线（只读零写入）：

```json
{
  "exercise_id": "…", "status": "open", "hint_level": 1, "solution_seen": false,
  "timeline": [
    {"type": "start", "time": "…", "label": "开始审题"},
    {"type": "attempt", "time": "…", "label": "提交答案，未通过", "answer": "A", "grade": "incorrect"},
    {"type": "hint", "time": "…", "label": "使用一级提示", "level": 1},
    {"type": "thinking", "time": "…", "label": "提交思路", "excerpt": "…"},
    {"type": "feedback", "time": "…", "label": "Tutor Agent 反馈/追问",
     "possible_problem": "…", "planner_source": "llm"}
  ],
  "current": {"label": "等待修改后重新提交"},
  "latest_feedback": {"feedback": "…", "possible_problem": "…", "socratic_question": "…",
                       "planner_source": "llm", "model_id": "deepseek-v4-flash"}
}
```

- 错误：404 题目不属于当前学生；400 illegal_state（题目已关闭）；401/422 同 v1.2。

## T13-B：Agentic RAG 教学链路

### POST /tutoring/rag

- 请求：`{"query": "…", "content_type": "explanation|example|hint|transfer", "concept_id": "…?",
          "exercise_id": "…?", "error_code": "…?", "student_level": "…?", "allowed_concept_ids": [...]?}`
  + `Idempotency-Key`。
- 链路：改写 → 混合检索（关键词+向量）→ 去重重排 → 课程/知识点/内容类型过滤（hint 做答案泄露过滤）
  → 可靠性阈值（0.30）→ 带引用生成（修复一次；越界引用/答案泄露禁止展示生成内容）→ trace 落库。
- 返回 `data`：

```json
{
  "trace_id": "uuid",
  "status": "ok | no_reliable_source | rag_fallback",
  "content": "带 [n] 引用的讲解正文（生成失败时为逐字摘录的规则摘要；no_reliable_source 时为 null）",
  "safe_message": "低于阈值时的安全提示（其余为 null）",
  "sources": [{"source_id": "res-c04-seg01", "title": "顶点式", "concept_id": "C04",
                "content_type": "hint", "heading": "符号陷阱", "excerpt": "…",
                "retrieval_score": 0.5, "rank": 1}],
  "raw_query": "…", "rewritten_query": "…",
  "planner_source": "llm | rule_fallback", "model_id": "deepseek-v4-flash | null",
  "fallback_reason": null, "flags": {"vector_fallback": false, "rag_fallback": false},
  "index_version": "课程包 sha256 前 16 位",
  "duration_ms": 3093
}
```

- 语义：检索分数只表示资料相关性，绝不进入掌握度/评分/路径；RAG 任意失败返回 200 +
  结构化状态，不阻塞答题与评分；`no_reliable_source` 时不得用无依据内容补全。

### GET /tutoring/rag/traces/{trace_id}

技术视图：raw/rewritten query、filters、index_version、candidates、reranked、final_sources、
status、content、planner_source、model_id、fallback_reason、flags、duration_ms、created_at。
归属校验，他人 404。

### GET /tutoring/rag/sources/{source_id}

来源查询：source_id/resource_id/course_id/concept_id/title/heading/content_type/text/index_version。
跨课程资源不可见 → 404。
