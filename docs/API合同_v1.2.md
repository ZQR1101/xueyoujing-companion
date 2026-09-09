# 学有所径 API / 数据合同 v1.2

- 日期：2026-09-08
- 状态：**正式生效（现行）**。基线为规格书 §12（v1.0）；v1.1 增补 R1～R5；本版增补 R6～R8（均由项目负责人确认）。
- 修订性质：均为增补与澄清，不改变 §7 掌握公式与 §6 数据语义。
- 任何后续变更必须先修订本文件，再实现。

## 修订记录

| 版本 | 编号 | 修订 | 内容 |
|---|---|---|---|
| v1.1 | R1 | 缺少令牌 → 401 | 未携带/无效演示令牌返回 **401** `invalid_token` |
| v1.1 | R2 | 诊断跳过机制 | 确认采用查询方案：`GET /assessments/{id}?after_exercise_id=<id>`（纯读、不算答错；被跳过题保持 open，可回头，完成后计入未测范围） |
| v1.1 | R3 | next_action.type 封闭枚举 | `next_question / complete_assessment / start_task / retry_exercise / show_result`（show_result 由 finish_session 决策返回，见 R8） |
| v1.1 | R4 | 数据契约补列 | `Question.purpose`（screening/practice/transfer/review）；`Goal.version`（可变实体乐观并发） |
| v1.1 | R5 | v0-seed 澄清 | 诊断后的临时拓扑种子不属于正式路径；**已退役**：T05 起由规则规划器生成 `policy_version=v1-rules` 的正式 Plan |
| v1.2 | R6 | 独立完整解析 | `Question` 增加 `private_solution`（Text，必填，与答案/分级提示分开存储）；`POST /exercises/{id}/solution` 返回该字段，禁止用提示拼装替代；公开 DTO 永不包含 |
| v1.2 | R7 | 讲解任务三态 | 讲解任务流：`lesson_presented`（内容展示，任务保持 active）→ `lesson_acknowledged`（学生确认，`POST /tasks/{id}/acknowledge`）→ `task_completed`（任务闭环）。**只有 task_completed 计入完成率；讲解不产生掌握证据**。事件集新增 lesson_presented / lesson_acknowledged |
| v1.2 | R8 | finish_session 真实闭环 | Agent 决策 finish_session 时将会话置为 **completed**（版本递增），此后 messages/start-next 拒绝（400），恢复视图无 resumable；决策记录与业务状态保持一致 |

## 通用约定

- 统一前缀 `/api/v1`；所有写请求必须带 `Idempotency-Key` 头（≤120 字符）。
- 幂等作用域 = 学生 + 方法 + 规范路径 + 键；同键同载荷返回首次响应，同键异载荷 409。
- 响应信封 `{"data","next_action","resource_version","trace_id"}`；错误信封 `{"error":{"code","message"},"trace_id"}`。
- 状态码：400 非法操作、401 未认证、404 不属于当前学生、409 版本/幂等冲突、422 输入格式错误、500 内部错误、503 模型不可用且无回退。
- 学生身份仅来自服务端演示令牌（本地演示能力，非公网认证系统）。
- 时间一律 UTC ISO 输出；外部写入 DTO 拒绝未知字段。

## 端点清单（截至 T07）

| 方法与路径 | 请求 | 返回（data 内） | resource_version |
|---|---|---|---|
| POST /demo-identities | display_name | token、student | null |
| POST /goals | course_id、target_concept_ids?、daily_minutes(5-120) | goal、session | session.version |
| POST /goals/{id}/replan | reason、expected_version（计划版本，无计划为 0） | plan、changed | plan.version |
| GET /goals/{id}/path | — | plan、nodes[]{status,reason,tasks}、previous_plan、stale | plan.version |
| GET /goals/{id}/tasks | ?date=YYYY-MM-DD（学生时区） | date、budget_minutes、pending_minutes、within_budget、tasks[] | plan.version |
| POST /sessions/{id}/diagnosis | expected_version（会话） | assessment、exercise、question、session | assessment.version |
| GET /sessions/{id} | — | session、goal、resumable（completed 会话为 null） | session.version |
| POST /sessions/{id}/start-next | expected_version（会话） | resumed、task、content（讲解）/exercise+question（练习/复习） | session.version |
| POST /sessions/{id}/pause | expected_version | session、resume_hint | session.version |
| POST /sessions/{id}/resume | expected_version | session、resume_location | session.version |
| POST /sessions/{id}/messages | text、expected_version | reply、decision{action,planner_source,model_id,fallback_reason,evidence_ids}、legal_actions、session_status、session_completed | session.version |
| GET /sessions/{id}/decisions | — | decisions[]（含 evidence_ids 引用与回退标记） | session.version |
| POST /sessions/{id}/reflection | text、expected_version | summary（确定性小结，含证据引用）、echo | session.version |
| POST /assessments/{id}/complete | expected_version（评估） | snapshot、uncovered_concept_ids、coverage、plan | assessment.version |
| GET /assessments/{id} | ?after_exercise_id（R2 跳过游标） | assessment、answered[]、next{exercise,question} | assessment.version |
| POST /exercises/{id}/attempts | answer、expected_version（练习） | attempt、mastery_delta、evidence、versions{exercise,assessment,session}、transfer_available | exercise.version |
| POST /exercises/{id}/hints | expected_version（练习） | level、hint（单层）、exercise_version | exercise.version |
| POST /exercises/{id}/solution | expected_version（练习） | solution_seen、answer、solution（R6）、note、exercise_version | exercise.version |
| POST /tasks/{id}/acknowledge | expected_version（任务）（R7，仅讲解任务） | task（status=completed） | task.version |
| GET /me/overview | — | student、goals[]{goal,coverage,mastery,latest_session}、recent_evidence、today_tasks | null |
| GET /me/mastery-history | ?concept_id | concept_id、formula_version、points[] | null |
| GET /healthz | —（无信封） | {"status":"ok"} | — |

## 数据契约补列（累计）

- `Question`：§6 必需字段 + `purpose`（R4）+ `private_solution`（R6，Text，必填，仅 solution 端点返回）。
- `Goal`：§6 字段 + `version`（R4）。
- `Plan`：+ `node_status_snapshot`（T05，升版判定依据）。
- 事件集（§11 基础上）：+ `lesson_presented`、`lesson_acknowledged`（R7）。

## 题目公开 DTO 字段（白名单）

`id, course_id, primary_concept_id, family_id, type, purpose, prompt, public_options, difficulty, version`
永不包含：`private_answer / private_hints / private_solution / numeric_config`。

## 讲解任务状态流（R7）

```text
queued --start-next--> active(lesson_presented) --acknowledge--> completed(task_completed)
                          │ 学生未确认 → 任务保持 active，计入待办分钟数，重复 start-next 返回同一任务
```

练习/复习任务流不变：start-next → active → 迁移题关闭 → task_completed。

## 错误码登记表

| code | HTTP | 触发 |
|---|---|---|
| invalid_token | 401 | 缺少或无效演示令牌 |
| missing_idempotency_key | 400 | 写请求未带 Idempotency-Key |
| illegal_state | 400 | 阶段/状态不合法（含会话已结束后的消息与任务启动、讲解未确认重复、提示超限） |
| insufficient_items | 400 | 题库无可用新题族 |
| resource_not_found | 404 | 资源不存在或不属于当前学生 |
| version_conflict | 409 | expected_version 过期（版本检查优先于状态检查） |
| idempotency_conflict | 409 | 同键不同载荷 |
| invalid_request | 422 | DTO 校验失败或答案格式不符（含防注入拒绝） |
| internal_error | 500 | 未处理异常 |

## next_action.type 登记表（R3）

| type | 首次启用 | 语义 |
|---|---|---|
| next_question | T04 | 诊断下一题 / 迁移题呈现 |
| complete_assessment | T04 | 本轮题目已尽，请完成诊断 |
| start_task | T05 | 开始下一个任务（present_lesson/assign_practice/schedule_review 决策映射至此） |
| retry_exercise | T06 | 原题重试（首答错误、offer_hint/assign_transfer 决策映射至此） |
| show_result | T07 | finish_session 决策返回（R8） |
