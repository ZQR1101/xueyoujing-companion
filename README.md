# 学有所径，伴有所成

具备学情诊断与持续规划能力的自适应伴学智能体（独立项目）。

> 状态：核心学习闭环、T13-B RAG、T14-B 反思记忆与 T14-D 成就激励均已实现。设计文档是
> [docs/学有所径_独立项目开发规格书_v2.md](docs/学有所径_独立项目开发规格书_v2.md)。

## 边界

- 本项目与 `ai-agent-study-assistant` 相互独立：不共享运行数据、不 import 其代码、不复制其凭据与用户数据；原项目仅作只读参考。
- 首版范围：一个学生、一个数学专题（初中二次函数，约 6 个知识点、300 道核验题）。
- 掌握度只认"独立、无提示、首答"的有效证据（按题族 family_id 去重）；检索分数不得作为学生能力。

## 目录（规划，见规格书 §14）

```text
backend/     Python + FastAPI + SQLAlchemy + SQLite
frontend/    React + TypeScript + Vite
curriculum/  课程包（二次函数知识点、题族、讲解资料）
docs/        本规格、接口、演示与决策记录
scripts/     初始化、演示种子、验证
```

## 快速启动

```bash
# 后端（Python 3.12，uv 管理，锁文件 backend/uv.lock）
cd backend
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000   # 探活: GET /healthz

# 前端（Node 20+，npm，锁文件 frontend/package-lock.json）
cd frontend
npm install
npm run dev                                                # http://localhost:5174（5173 已留给其他项目）
```

首次运行前复制 `.env.example` 为 `.env`（不提交）。

## 开发方式

按规格书第 15 章分批执行工单：T01 独立工程 → T02 数据与事务 → … → T09 演示与交付。
每次只做一个工单，完成并验证后再进入下一项。

当前进度：**T02～T08、T10-B～T14-B 以及 T14-D 激励投影已完成并自验**。当前后端全量 **123 项测试通过**；前端 TypeScript 与 Vite 生产构建通过。API 合同基线为 [v1.2](docs/API合同_v1.2.md)，后续能力见 [API 合同增补](docs/API合同_增补_T10-T14.md)。

T14-B 已提供学习小结、证据校验、版本化记忆、冲突链、纠错/撤销、下一次建议和 Planner 有效记忆上下文。T14-D 的 25 枚徽章全部由后端真实事件计算，未达成徽章不返回核发证据；积分不等同于掌握度。

## 验证

```bash
cd backend
.venv\Scripts\python.exe -m pytest -q

cd ..\frontend
npm run build
```

服务启动后可用下面命令做路演前只读预检（不会发送模型请求）：

```bash
python scripts/demo_preflight.py
```

赛事闭环测试：`backend/tests/test_t14b_reflection.py::test_competition_demo_closed_loop_and_refresh_recovery`。启动后可访问 `GET /readyz` 检查课程包、RAG 索引与模型配置；前端 API 地址可通过 `frontend/.env` 的 `VITE_API_BASE_URL` 配置。T14-B 交付说明与演示步骤见 [T14B 工单交付记录](docs/T14B-工单交付记录.md)、[比赛验收与演示脚本](docs/比赛验收与演示脚本.md) 和 [商业化与落地方案](docs/商业化与落地方案.md)。
