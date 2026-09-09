# 学有所径，伴有所成

具备学情诊断与持续规划能力的**自适应伴学智能体**。它能解释：你现在适合学什么、为什么、遇到困难怎么办，以及上次的学习如何影响今天的安排。

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-6.0-3178C6?logo=typescript&logoColor=white)
![Tests](https://img.shields.io/badge/tests-123%20passing-brightgreen)

首版聚焦一个学生、一个数学专题（初中二次函数：约 6 个知识点、300 道人工核验题），未来通过课程包扩展学科。

## 核心特性

- **学情诊断**：6 道初筛题快速定位。未测试的知识点如实显示"尚未评估"，跳过不算答错，中断后刷新可继续。
- **自适应学习路径**：Planner 综合知识点先修关系、当前掌握度、每日时间预算、未完成任务与长期记忆，生成可解释的下一步安排；新的有效证据会自动触发路径重算。
- **脚手架式辅导**：答错先给分层提示，再由 AI 结合课程资料做概念讲解（RAG 检索：查询改写、课程过滤、重排、真实来源引用）。在提示下答对会被如实标记为"辅助完成"，不计入独立掌握。
- **迁移验证**：只有在新题上"独立、无提示、首答"正确，才产生新的掌握证据（按题族去重，防止重复刷题虚增掌握）。
- **学习反思与长期记忆**：自动生成"已掌握 / 待巩固 / 下次建议"小结，附证据编号。记忆版本化存储、可纠错、可撤销；被标记不准确的记忆会自动排除出后续规划上下文。
- **成就激励**：25 枚徽章全部由真实学习事件计算，未达成不给核发证据；任务奖励与匿名排行榜。
- **可重复演示**：内置 mock 模型提供者，离线即可跑通完整闭环；切换真实模型（任意 OpenAI 兼容接口）后，模型/检索/记忆失败均有结构化回退。前端顶栏实时显示当前运行模式，避免把离线回退误当成在线模型。

## 架构

```text
React + TypeScript + Vite 前端
        │  HTTP (JSON, /api/v1)
        ▼
FastAPI ─── 学习协调器 Coordinator
             ├─ 诊断与确定性评分
             ├─ 掌握状态投影（只认有效证据）
             ├─ Planner：先修图 + 预算 + 记忆 → 学习路径
             ├─ 工具注册 / RAG 课程资料检索
             ├─ LLM 网关（mock / OpenAI 兼容，失败回退）
             └─ 版本化长期记忆（可纠错）
                    │
                    ▼
             SQLite（唯一事实源）+ Alembic 迁移
```

## 快速开始

前置：[uv](https://docs.astral.sh/uv/)（Python 3.12 由 uv 托管）、Node 20+。

```bash
# 1. 后端
cd backend
uv sync                                          # 安装依赖（锁定于 uv.lock）
uv run alembic upgrade head                      # 建表
uv run python ../../scripts/import_curriculum.py # 导入课程包（幂等）
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
# 探活 GET /healthz；就绪详情（课程/索引/模型模式）GET /readyz

# 2. 前端（另开一个终端）
cd frontend
npm install
npm run dev    # http://localhost:5174（5173 已留给其他项目）
```

首次运行前，把根目录的 `.env.example` 复制为 `.env`（不提交）。默认 `LLM_PROVIDER=mock`，离线可完整演示；接真实模型时改为 `openai` 并填 `LLM_BASE_URL` / `LLM_MODEL_ID` / `LLM_API_KEY`（附 DeepSeek 示例，见 `.env.example` 内注释）。前端如需自定义 API 地址，在 `frontend/.env` 配置 `VITE_API_BASE_URL`。

## 常用命令

| 命令 | 说明 |
|---|---|
| `cd backend && uv run pytest -q` | 后端全量测试（当前 123 项） |
| `cd frontend && npm run build` | 前端类型检查 + 生产构建 |
| `cd frontend && npm run lint` | 前端 lint（oxlint） |
| `python scripts/demo_preflight.py` | 演示前只读预检 `/healthz` 与 `/readyz`，不发送模型请求 |

## 目录结构

```text
backend/          FastAPI + SQLAlchemy + SQLite（uv 管理依赖）
  app/api/            HTTP 路由、DTO、幂等与统一错误封装
  app/services/       学习协调、诊断、规划、辅导、反思等业务逻辑
  app/domain/         领域模型与纯计算（掌握度、先修图、评分）
  app/infrastructure/ 数据库、LLM 网关、RAG 索引、课程导入
  alembic/            数据库迁移
  tests/              pytest 全量测试
frontend/         React 19 + TypeScript + Vite
  src/pages/          学情总览、诊断、路径、练习工作台、成就等页面
curriculum/       课程包：二次函数知识点、核验题库、讲解资料
docs/             规格书、API 合同、交付记录、演示与商业化文档
scripts/          课程导入、题库生成、演示预检
```

## 项目文档

- [独立项目开发规格书 v2](docs/学有所径_独立项目开发规格书_v2.md) —— 产品与工程设计全文
- [API 合同 v1.2](docs/API合同_v1.2.md)（[增补 T10–T14](docs/API合同_增补_T10-T14.md)）—— 接口基线
- [比赛验收与演示脚本](docs/比赛验收与演示脚本.md) —— 3～5 分钟现场演示流程
- [商业化与落地方案](docs/商业化与落地方案.md) —— 部署形态与验证指标
- [工单交付记录](docs/) —— 各阶段实施与验证记录

## 范围与声明

- 掌握度只认"独立、无提示、首答"的有效证据（按题族 `family_id` 去重）；检索相关性分数不得作为学生能力。
- 未经过教学实验验证的规则统一称为"启发式策略"，不宣称已验证的学习效果；积分与徽章不等同于掌握度。
- 本项目与 `ai-agent-study-assistant` 相互独立：不共享运行数据、不引用其代码、不复制其凭据，原项目仅作只读参考。
