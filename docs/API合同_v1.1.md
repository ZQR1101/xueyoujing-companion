# 学有所径 API / 数据合同 v1.1

- 日期：2026-09-08
- 状态：**正式生效**。基线为规格书 §12（v1.0）；本文件记录经项目负责人确认的修订。
- 修订性质：均为**增补与澄清**，不改变 §12 已定义的接口形状、掌握公式（§7）与数据语义（§6）。
- 任何后续变更（含 T05/T06/T07 新增 next_action 取值）必须先修订本文件，再实现。

## 1. 修订记录（v1.0 → v1.1，均由项目负责人 2026-09-08 确认）

| 编号 | 修订 | 内容 |
|---|---|---|
| R1 | 缺少令牌 → 401 | 未携带 `Authorization: Bearer <token>` 或令牌无效时返回 **401** `{"error":{"code":"invalid_token"}}`（原实现 400，v1.0 错误码封闭集未列 401，现正式纳入） |
| R2 | 诊断跳过机制 | **确认采用查询方案**：`GET /api/v1/assessments/{id}?after_exercise_id=<exercise_id>` 返回其后第一个未答题（纯读、不写状态、不算答错）。被跳过的题保持 `open`，学生刷新后可回到该题；直至诊断完成仍未答的题计入未测范围。规格书 §4.1「跳过不算答错，刷新后继续」由该机制承载，不新增写端点 |
| R3 | next_action.type 封闭枚举 | `type` 取值限定为：`next_question` / `complete_assessment` / `start_task` / `retry_exercise` / `show_result`。其中 `next_question`、`complete_assessment` 自 T04 起使用；`start_task`（T05）、`retry_exercise`、`show_result`（T06）为预留，实现工单启用时无需再改合同 |
| R4 | 数据契约补列 | `Question` 增加 `purpose`（screening / practice / transfer / review，对应 §8 题族四类用途，随课程包发布）；`Goal` 增加 `version`（整数，可变实体乐观并发，§6 总则条款优先于 v1.0 字段表的省略）。两者均在响应 DTO 中可见 |
| R5 | v0-seed 语义澄清 | 诊断完成（`POST /assessments/{id}/complete`）返回的 `plan.policy_version = "v0-seed"` **仅是诊断阶段生成的拓扑种子**（目标概念按依赖图稳定排序），**不属于正式个性化学习路径**。T05 路径规划器上线后应重新生成正式 Plan（前置约束、排序规则、预算、版本差异均按规格书 §9），v0-seed 不作为路径展示与决策依据 |

## 2. 通用约定（沿规格书 §12，明确化）

- 统一前缀 `/api/v1`；所有写请求必须带 `Idempotency-Key` 头（≤120 字符）。
- 幂等作用域 = 学生 + 方法 + 规范路径 + 键；同键同载荷返回首次响应，同键异载荷 409 `idempotency_conflict`。
- 响应信封：`{"data", "next_action", "resource_version", "trace_id"}`；`next_action` 可为 null；`resource_version` 对应本接口主要资源。
- 错误信封：`{"error":{"code","message"},"trace_id"}`；状态码：400 非法操作、**401 未认证（R1）**、404 不存在或不属于当前学生、409 版本/幂等冲突、422 输入格式错误、503 模型不可用且无回退。
- 学生身份只来自服务端演示令牌；演示令牌是本地演示能力，不是公网认证系统。
- 外部写入 DTO 拒绝未知字段；时间一律 UTC ISO 输出（`+00:00`）。

## 3. 端点清单（截至 T04，另见规格书 §12 的 T05+ 端点）

| 方法与路径 | 请求 | 返回（data 内） | resource_version |
|---|---|---|---|
| POST /demo-identities | display_name | token、student | null |
| POST /goals | course_id、target_concept_ids?、daily_minutes(5-120) | goal（含 version）、session | session.version |
| POST /sessions/{id}/diagnosis | expected_version（会话版本） | assessment、exercise、question（公开 DTO）、session | assessment.version |
| GET /sessions/{id} | — | session、goal、resumable（assessment/exercise/question） | session.version |
| GET /assessments/{id} | ?after_exercise_id（R2 跳过游标，可选） | assessment、answered[]、next{exercise,question} | assessment.version |
| POST /assessments/{id}/complete | expected_version（评估版本） | snapshot[]、uncovered_concept_ids、coverage、plan | assessment.version |
| POST /exercises/{id}/attempts | answer、expected_version（练习版本） | attempt、mastery_delta、evidence、versions{exercise,assessment,session} | exercise.version |
| GET /me/overview | — | student、goals[]{goal,coverage,mastery,latest_session}、recent_evidence、today_tasks | null |
| GET /me/mastery-history | ?concept_id | concept_id、formula_version、points[]{before,after,evidence/attempt} | null |
| GET /healthz | —（无信封） | {"status":"ok"} | — |

题目公开 DTO 字段：`id, course_id, primary_concept_id, family_id, type, purpose(R4), prompt, public_options, difficulty, version`；**永远不包含** `private_answer / private_hints / numeric_config`（A15）。

## 4. 错误码登记表

| code | HTTP | 触发 |
|---|---|---|
| invalid_token | 401 | 缺少或无效演示令牌（R1） |
| missing_idempotency_key | 400 | 写请求未带 Idempotency-Key |
| illegal_state | 400 | 阶段/状态不合法（如练习已关闭后重复提交、非诊断阶段提交） |
| insufficient_items | 400 | 题库无可用新题族（A14），保留现有估计 |
| resource_not_found | 404 | 资源不存在或不属于当前学生（A11） |
| version_conflict | 409 | expected_version 过期（A09；版本检查优先于状态检查） |
| idempotency_conflict | 409 | 同键不同载荷 |
| invalid_request | 422 | DTO 校验失败或答案不符合该题格式（含防注入拒绝） |
| internal_error | 500 | 未处理异常 |

## 5. next_action.type 登记表（R3）

| type | 首次启用 | data 关联 | 语义 |
|---|---|---|---|
| next_question | T04 | target_id = exercise_id | 答完一题后继续下一题 |
| complete_assessment | T04 | target_id = assessment_id | 本轮题目已尽，请完成诊断 |
| start_task | T05（预留） | target_id = task_id | 开始下一个任务 |
| retry_exercise | T06（预留） | target_id = exercise_id | 原题重试（辅导循环） |
| show_result | T06（预留） | target_id = exercise_id | 展示本步结果/解析 |

新增取值 = 合同修订（本文件升版），禁止实现层私加。
