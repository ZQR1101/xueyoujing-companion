# API 合同增补：T10～T14

- 日期：2026-09-09
- 基线：[API 合同 v1.2](API合同_v1.2.md)
- 本文件记录已实现的 T14-B 反思记忆与 T14-D 激励接口；T10～T13 的详细字段沿用各工单交付记录。

## 通用约定

- 所有写请求必须携带 `Idempotency-Key`。
- 身份只从 Bearer Token 解析；URL 或请求体不能指定学生。
- 越权资源统一返回 `404 resource_not_found`，避免泄露其他学生数据。
- 正常响应仍使用 `data / next_action / resource_version / trace_id` 信封。
- T14 只写反思、记忆和激励事件，不修改 `MasteryState`、原评分或 `Plan`。

## T14-B 接口

| 方法与路径 | 请求 | 主要返回 |
|---|---|---|
| POST `/api/v1/sessions/{id}/reflection` | `text?`、`expected_version?`、`force_llm_failure?` | `learned`、`still_uncertain`、`evidence_summary`、`learning_characteristics`、`next_recommendation`、`planner_source`、`fallback_reason`、`memory_write_status` |
| GET `/api/v1/sessions/{id}/reflection` | — | 最近一次持久化小结 |
| GET `/api/v1/sessions/{id}/reflection-overview` | — | 小结 + `active_memories`，供 T14-F 使用 |
| GET `/api/v1/sessions/{id}/next-recommendation` | — | 当前小结中的下一次建议 |
| GET `/api/v1/courses/{course_id}/memories?concept_id=` | — | 当前学生、当前课程的 active 记忆 |
| POST `/api/v1/memories/{id}/correction` | `status=disputed|invalidated` | 更新后的记忆；保留原记录和证据 |
| POST `/api/v1/memories/{id}/restore` | — | 撤销纠错，恢复为 active |
| GET `/api/v1/memories/{id}/chain` | — | 从当前版本沿 `supersedes_id` 回溯的完整链 |

学习事实字段：`memory_id, student_id, course_id, concept_id, type, content, evidence_event_ids, status, created_at, version, supersedes_id, source_session_id`。

`planner_source` 为 `llm` 或 `reflection_rule_fallback`。模型超时、两次非法 JSON、未知/缺失证据、越权知识点或禁用掌握表述都会回退；回退仍只依据真实事件。记忆写入失败时接口仍返回小结，`memory_write_status=failed:<Exception>`。

## T14-D 接口

| 方法与路径 | 请求 | 主要返回 |
|---|---|---|
| GET `/api/v1/me/motivation` | — | 积分、等级、连续天数、已获徽章、25 枚 `badge_catalog`、可领取奖励 |
| GET `/api/v1/motivation/leaderboard` | — | 匿名排行 `rank/display_name/points` |
| POST `/api/v1/me/motivation/rewards/{reward_id}/claim` | — | 奖励领取结果；重复领取不可用 |

每个 `badge_catalog` 条目含 `id, name, reason, acquired, progress{current,target}, evidence_event_ids`。只有满足规则的徽章才会 `acquired=true` 并返回真实来源；未达成条目的证据数组为空。

## 主要错误码

- `invalid_token`：缺失或无效令牌（401）。
- `resource_not_found`：会话、课程或记忆不属于当前学生（404）。
- `idempotency_conflict`：同键异载荷（409）。
- `validation_error`：字段或状态值非法（422）。
- `internal_error`：未被局部回退覆盖的服务错误（500）。

