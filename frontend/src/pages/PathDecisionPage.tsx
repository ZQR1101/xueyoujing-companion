/** T11-D 当前路径 · Agent 路径决策：stitch stitch_ (12) 原版移植（独立布局，含页内 aside/footer）。
 *  真实数据：节点状态/估计 ← GET /goals/{id}/path + /me/overview；
 *  调整前后/原因/候选/当前任务 ← T11-B 路径决策接口（GET 最近一次，首次进入自动生成）。
 *  「演示状态」仅切换页面视图（正常生成/路径保持不变/规划失败），不改业务数据。 */
import { useCallback, useEffect, useState } from 'react';

import { ApiError } from '../api/client';
import { createPathDecision, getOverview, getPath, getPathDecision } from '../api/endpoints';
import type { MasteryEntry, OverviewData, PathData, PathDecisionData } from '../api/types';
import { navigate } from '../lib/router';

type DemoState = 'normal' | 'unchanged' | 'failed';

function pctOf(estimate: number | null): string {
  return estimate === null ? '' : ` · ${Math.round(estimate * 100)}%`;
}

const TYPE_LABEL: Record<string, string> = { lesson: '讲解', practice: '练习', review: '复习' };

export function PathDecisionPage() {
  const [overview, setOverview] = useState<OverviewData | null>(null);
  const [path, setPath] = useState<PathData | null>(null);
  const [decision, setDecision] = useState<PathDecisionData | null>(null);
  const [demoState, setDemoState] = useState<DemoState>('normal');
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  const goalId = overview?.goals[0]?.goal.id ?? null;
  const mastery: MasteryEntry[] = overview?.goals[0]?.mastery ?? [];
  const estimateOf = (cid: string) => mastery.find((m) => m.concept_id === cid)?.estimate ?? null;

  const applyDecision = useCallback(async (gid: string, pathData: PathData) => {
    try {
      const d = await getPathDecision(gid);
      setDecision(d);
      setDemoState(d.changed ? 'normal' : 'unchanged');
    } catch {
      // 尚无决策：生成一次（等价于进入页面即运行路径 Agent）
      const planVersion = pathData.plan?.version ?? 0;
      const d = await createPathDecision(gid, planVersion);
      setDecision(d);
      setDemoState(d.changed ? 'normal' : 'unchanged');
    }
  }, []);

  const load = useCallback(async () => {
    const data = await getOverview();
    setOverview(data);
    const entry = data.goals[0];
    if (!entry) return;
    const pathData = await getPath(entry.goal.id).catch(() => null);
    setPath(pathData);
    if (pathData) await applyDecision(entry.goal.id, pathData);
  }, [applyDecision]);

  useEffect(() => {
    load().catch((e: ApiError) => setError(e.message));
  }, [load]);

  async function replan() {
    if (!goalId || working) return;
    setWorking(true);
    setError(null);
    try {
      const d = await createPathDecision(goalId, decision?.current_plan_version ?? path?.plan?.version ?? 0);
      setDecision(d);
      setDemoState(d.changed ? 'normal' : 'unchanged');
    } catch (e) {
      setDemoState('failed');
      setError(e instanceof ApiError ? e.message : '路径决策失败');
    } finally {
      setWorking(false);
    }
  }

  if (error && !overview) {
    return (
      <main className="min-h-screen bg-surface-bg pt-16">
        <div className="max-w-[900px] mx-auto px-6 py-space-xl">
          <div className="p-space-md rounded-xl bg-error-container text-on-error-container font-body-md">{error}</div>
        </div>
      </main>
    );
  }
  if (!overview) {
    return (
      <main className="min-h-screen bg-surface-bg pt-16">
        <div className="p-space-xl text-center text-outline font-body-md">正在加载路径决策…</div>
      </main>
    );
  }

  const entry = overview.goals[0];
  const student = overview.student;

  // ---------- 冷启动：尚无目标 ----------
  if (!entry || !path) {
    return (
      <main className="min-h-screen bg-surface-bg pt-16">
        <div className="max-w-[900px] mx-auto px-6 py-space-xl flex flex-col gap-space-md">
          <h1 className="text-2xl font-bold tracking-tight text-on-surface font-serif">你的下一步，为什么这样安排</h1>
          <div className="p-space-lg rounded-xl bg-white border border-outline-border shadow-xs text-center">
            <p className="font-body-md text-on-ink-variant">还没有学习计划。先完成一次诊断，路径 Agent 才能为你安排最合适的任务。</p>
            <button
              className="mt-space-md px-space-lg py-space-xs rounded-lg bg-primary-container text-on-primary font-title-md text-title-md shadow-sm hover:bg-primary-hover transition-colors"
              onClick={() => navigate('/profile')}
              type="button"
            >
              去我的学情开始诊断
            </button>
          </div>
      </div>
      </main>
    );
  }

  // ---------- 节点列表（真实状态 + 掌握估计） ----------
  const nodes = path.nodes;
  const currentIndex = nodes.findIndex(
    (n) => !['mastered', 'locked'].includes(n.status) && n.eligible,
  );
  const currentIdx = currentIndex === -1 ? 0 : currentIndex;
  const focusNode = nodes[currentIdx];
  const focusEstimate = estimateOf(focusNode?.concept_id ?? '');
  const pendingMinutes = nodes
    .flatMap((n) => n.tasks)
    .filter((t) => ['queued', 'active'].includes(t.status))
    .reduce((s, t) => s + t.estimated_minutes, 0);
  const remainingMinutes = Math.max(student.daily_minutes - pendingMinutes, 0);

  // 调整前后：第一个发生变化的槽位（用于「原计划」叙述）
  const before = decision?.plan_before?.ordered_concept_ids ?? [];
  const after = decision?.plan_after?.ordered_concept_ids ?? [];
  const changedSlot = after.find((cid, i) => before[i] !== cid) ?? focusNode?.concept_id;
  const beforeTitle =
    nodes.find((n) => n.concept_id === (before.find((cid) => !after.includes(cid)) ?? changedSlot))?.title ?? changedSlot;
  const lockedCount = nodes.filter((n) => n.status === 'locked').length;
  const agentMeta = decision
    ? `Agent ${decision.model_id === 'mock' ? 'mock 模拟' : decision.model_id ?? '规则'} · ${decision.duration_ms}ms`
    : '';

  return (
    <div className="pl-16 md:pl-64 min-h-screen bg-surface-bg">
      <div className="max-w-[1180px] mx-auto px-4 md:px-8 pt-20 pb-6 w-full">
        <div className="flex flex-col gap-4 min-w-0">
          {/* 页头 + 演示状态 + 重新规划 */}
          <header className="flex flex-col md:flex-row md:items-end justify-between gap-3 pb-1 border-b border-outline-border/60">
            <div className="flex flex-col gap-1">
              <div className="flex items-center gap-2">
                <h1 className="text-2xl md:text-[24px] font-bold tracking-tight text-on-surface font-serif">你的下一步，为什么这样安排</h1>
                <span className="text-xs font-normal px-2 py-0.5 whitespace-nowrap bg-primary-light text-primary-container border border-primary-container/20 rounded-md shrink-0">Agent 路径决策</span>
              </div>
              <p className="text-xs text-on-ink-variant">系统会结合你的掌握情况、先修关系和今日学习时间，安排当前最合适的任务。</p>
            </div>
            <div className="flex items-center gap-2 self-start md:self-auto shrink-0">
              <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-surface-subtle/80 border border-outline-border/60 text-xs">
                <span className="text-on-ink-variant text-[11px] font-medium whitespace-nowrap">演示状态:</span>
                <select
                  className="bg-transparent text-xs font-medium text-on-surface border-none p-0 focus:ring-0 cursor-pointer outline-none whitespace-nowrap"
                  onChange={(e) => setDemoState(e.target.value as DemoState)}
                  value={demoState}
                >
                  <option value="normal">正常生成 (微调推荐)</option>
                  <option value="unchanged">路径保持不变</option>
                  <option value="failed">规划失败 (容灾)</option>
                </select>
              </div>
              <button
                className="px-4 py-2 rounded-lg bg-white border border-outline-border hover:bg-surface-subtle text-xs font-semibold text-on-surface flex items-center justify-center gap-1.5 shadow-xs transition-all shrink-0 whitespace-nowrap disabled:opacity-60"
                disabled={working}
                onClick={replan}
                type="button"
              >
                <span className="material-symbols-outlined text-[15px] text-primary-container shrink-0">refresh</span>
                <span className="whitespace-nowrap">{working ? '规划中…' : '重新规划'}</span>
              </button>
            </div>
          </header>

          {/* 容灾横幅（规划失败态） */}
          {demoState === 'failed' && (
            <section className="p-3.5 rounded-xl bg-secondary-light border border-secondary-border flex items-center justify-between gap-3" id="disaster-banner">
              <div className="flex items-center gap-2.5">
                <span className="material-symbols-outlined text-secondary-accent text-[20px]">warning</span>
                <div className="text-xs">
                  <span className="font-bold text-secondary-dark">暂时无法完成新的路径规划</span>
                  <p className="text-on-ink-variant mt-0.5">{error ?? '你的已有学习进度不会丢失，当前计划仍然有效。'}</p>
                </div>
              </div>
              <button
                className="px-3 py-1 rounded-lg bg-white border border-secondary-border text-xs font-semibold text-secondary-dark hover:bg-secondary-light transition-all shrink-0 shadow-xs"
                onClick={replan}
                type="button"
              >
                重试规划
              </button>
            </section>
          )}

          {/* 调整说明卡（正常/保持 两态） */}
          {decision && demoState !== 'failed' && (
            <section className="rounded-xl bg-white border border-outline-border shadow-xs overflow-hidden transition-all duration-200" id="adaptive-card">
              {decision.changed ? (
                <div className="p-4 flex flex-col md:flex-row items-start md:items-center justify-between gap-3 bg-secondary-light/40 border-l-4 border-secondary-accent" id="state-normal-card">
                  <div className="flex items-start gap-3 flex-1 min-w-0">
                    <div className="w-8 h-8 rounded-lg bg-white text-secondary-accent border border-secondary-border flex items-center justify-center shrink-0 mt-0.5 shadow-xs">
                      <span className="material-symbols-outlined text-[18px]">tune</span>
                    </div>
                    <div className="flex flex-col gap-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-xs font-bold px-2 py-0.5 rounded bg-secondary-accent/10 text-secondary-dark border border-secondary-border">这次调整了什么</span>
                        <span className="text-[11px] text-on-ink-variant">今日剩余 {remainingMinutes} 分钟 · 动态调整{agentMeta ? ` · ${agentMeta}` : ''}</span>
                      </div>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-x-4 gap-y-1 text-xs text-on-ink-variant mt-0.5">
                        <div><strong className="text-on-surface font-semibold">原计划：</strong>直接进入“{beforeTitle}”练习</div>
                        <div><strong className="text-primary-container font-semibold">当前安排：</strong>{decision.selected_action.label || decision.reason}</div>
                      </div>
                      <p className="text-xs text-on-ink-variant mt-0.5">
                        <strong className="text-on-surface font-semibold">调整原因：</strong>{decision.reason}
                      </p>
                    </div>
                  </div>
                  <button
                    className="px-3 py-1.5 rounded-lg bg-white hover:bg-surface-subtle text-primary-container border border-outline-border text-xs font-semibold flex items-center gap-1 shrink-0 self-end md:self-center transition-colors shadow-xs"
                    onClick={() => document.getElementById('rationale-details')?.setAttribute('open', '')}
                    type="button"
                  >
                    <span>查看决策依据</span>
                    <span className="material-symbols-outlined text-[16px]">expand_more</span>
                  </button>
                </div>
              ) : (
                <div className="p-4 bg-status-mastered-bg/50 border-l-4 border-status-mastered flex items-center justify-between gap-3" id="state-insufficient-card">
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-lg bg-white text-status-mastered border border-status-mastered/30 flex items-center justify-center shrink-0 shadow-xs">
                      <span className="material-symbols-outlined text-[18px]">verified</span>
                    </div>
                    <div className="flex flex-col gap-0.5 text-xs">
                      <span className="font-bold text-on-surface text-sm">路径保持不变 · 节奏平稳有序{agentMeta ? ` · ${agentMeta}` : ''}</span>
                      <span className="text-on-ink-variant">{decision.reason || '目前还没有足够的新证据调整学习路径。系统会暂时保持当前计划，继续收集你的作答表现。'}</span>
                    </div>
                  </div>
                  <button
                    className="px-3 py-1.5 rounded-lg bg-white hover:bg-surface-subtle text-primary-container border border-outline-border text-xs font-semibold flex items-center gap-1 shrink-0 transition-colors shadow-xs"
                    onClick={() => document.getElementById('rationale-details')?.setAttribute('open', '')}
                    type="button"
                  >
                    <span>查看依据</span>
                    <span className="material-symbols-outlined text-[16px]">expand_more</span>
                  </button>
                </div>
              )}
            </section>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-start">
            {/* 核心先修路径 */}
            <section className="lg:col-span-7 flex flex-col gap-2.5">
              <div className="flex items-center justify-between px-1">
                <div className="flex items-center gap-1.5">
                  <span className="material-symbols-outlined text-primary-container text-[18px]">account_tree</span>
                  <h2 className="text-xs md:text-sm font-bold text-on-surface">核心先修路径</h2>
                  <span className="text-[11px] text-on-ink-variant">(依循因果递进)</span>
                </div>
                <div className="flex items-center gap-2.5 text-[11px] text-on-ink-variant">
                  <span className="inline-flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-status-mastered" />已掌握</span>
                  <span className="inline-flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-secondary-accent" />需巩固</span>
                  <span className="inline-flex items-center gap-1 font-semibold text-primary-container"><span className="w-1.5 h-1.5 rounded-full bg-primary-container" />当前节点</span>
                  <span className="inline-flex items-center gap-1 text-status-locked"><span className="material-symbols-outlined text-[11px]">lock</span>待解锁</span>
                </div>
              </div>
              <div className="p-3.5 rounded-xl bg-white border border-outline-border shadow-xs flex flex-col gap-2">
                {nodes.map((node, i) => {
                  const estimate = estimateOf(node.concept_id);
                  const isCurrent = i === currentIdx;
                  if (node.status === 'locked') {
                    return (
                      <div className="flex items-center justify-between p-2.5 rounded-lg bg-surface-subtle/40 border border-outline-border/40 text-xs text-status-locked" key={node.concept_id}>
                        <div className="flex items-center gap-2.5">
                          <span className="w-5 h-5 rounded-full bg-surface-subtle text-status-locked flex items-center justify-center"><span className="material-symbols-outlined text-[13px]">lock</span></span>
                          <span className="font-normal text-on-ink-variant">{i + 1}. {node.title}</span>
                        </div>
                        <span className="text-[11px] text-status-locked flex items-center gap-0.5"><span className="material-symbols-outlined text-[11px]">lock</span>待解锁</span>
                      </div>
                    );
                  }
                  if (isCurrent) {
                    return (
                      <div className="flex items-center justify-between p-2.5 rounded-lg bg-primary-light/40 border-2 border-primary-container text-xs shadow-xs" key={node.concept_id}>
                        <div className="flex items-center gap-2.5">
                          <span className="w-5 h-5 rounded-full bg-primary-container text-white flex items-center justify-center shadow-xs"><span className="material-symbols-outlined text-[13px]">play_arrow</span></span>
                          <span className="font-bold text-sm text-primary-container">{i + 1}. {node.title}</span>
                        </div>
                        <span className="px-2 py-0.5 rounded text-[11px] font-bold bg-primary-container text-white flex items-center gap-1">
                          <span className="w-1.5 h-1.5 rounded-full bg-white animate-pulse" />
                          当前学习{pctOf(focusEstimate) || ' · 尚未评估'}
                        </span>
                      </div>
                    );
                  }
                  if (node.status === 'mastered') {
                    return (
                      <div className="flex items-center justify-between p-2.5 rounded-lg bg-surface-subtle/70 border border-outline-border/40 text-xs" key={node.concept_id}>
                        <div className="flex items-center gap-2.5">
                          <span className="w-5 h-5 rounded-full bg-status-mastered-bg text-status-mastered flex items-center justify-center"><span className="material-symbols-outlined text-[13px]">check</span></span>
                          <span className="font-medium text-on-surface">{i + 1}. {node.title}</span>
                        </div>
                        <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-status-mastered-bg text-status-mastered">已掌握{pctOf(estimate)}</span>
                      </div>
                    );
                  }
                  if (node.status === 'unassessed') {
                    return (
                      <div className="flex items-center justify-between p-2.5 rounded-lg bg-surface-subtle/70 border border-outline-border/40 text-xs" key={node.concept_id}>
                        <div className="flex items-center gap-2.5">
                          <span className="w-5 h-5 rounded-full bg-surface-subtle text-status-locked flex items-center justify-center"><span className="material-symbols-outlined text-[13px]">radio_button_unchecked</span></span>
                          <span className="font-medium text-on-surface">{i + 1}. {node.title}</span>
                        </div>
                        <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-surface-subtle text-on-ink-variant border border-outline-border/40">尚未评估</span>
                      </div>
                    );
                  }
                  return (
                    <div className="flex items-center justify-between p-2.5 rounded-lg bg-secondary-light/40 border border-secondary-border text-xs" key={node.concept_id}>
                      <div className="flex items-center gap-2.5">
                        <span className="w-5 h-5 rounded-full bg-secondary-light text-secondary-accent flex items-center justify-center"><span className="material-symbols-outlined text-[13px]">sync</span></span>
                        <span className="font-medium text-on-surface">{i + 1}. {node.title}</span>
                      </div>
                      <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-secondary-light text-secondary-dark border border-secondary-border">需要巩固{pctOf(estimate)}</span>
                    </div>
                  );
                })}
              </div>
            </section>

            {/* 当前学习任务 */}
            <aside className="lg:col-span-5 flex flex-col gap-3 lg:sticky lg:top-20">
              <div className="p-5 rounded-xl bg-white border border-outline-border shadow-xs flex flex-col gap-3.5">
                <div className="flex items-start justify-between pb-2.5 border-b border-surface-subtle">
                  <div className="flex flex-col gap-0.5">
                    <span className="text-xs text-primary-container font-semibold">核心焦点</span>
                    <h3 className="text-base font-bold text-on-surface font-serif">当前学习任务</h3>
                  </div>
                  <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-primary-light text-primary-container border border-primary-container/20 whitespace-nowrap">
                    {focusEstimate === null ? '尚未评估' : `掌握度 ${Math.round((focusEstimate ?? 0) * 100)}%`}
                  </span>
                </div>
                <div className="p-4 rounded-xl bg-primary-light/30 border border-primary-container/30 flex flex-col gap-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold text-primary-container">{focusNode?.title ?? '—'}</span>
                    {decision?.current_task && (
                      <span className="text-[11px] font-medium text-on-ink-variant whitespace-nowrap">预计用时 {decision.current_task.estimated_minutes} 分钟</span>
                    )}
                  </div>
                  <h4 className="text-sm md:text-base font-bold text-on-surface leading-snug">
                    {decision?.selected_action.label || (decision?.current_task ? `继续「${focusNode?.title}」${TYPE_LABEL[decision.current_task.type] ?? '任务'}` : '等待安排')}
                  </h4>
                  <p className="text-xs text-on-ink-variant leading-relaxed">{decision?.reason || '完成当前学习后，系统会安排下一步。'}</p>
                </div>
                <div className="flex flex-col gap-2 pt-1">
                  <button
                    className="w-full py-3 px-4 rounded-xl bg-primary-container hover:bg-primary-hover active:scale-[0.99] text-white text-sm font-bold flex items-center justify-center gap-2 shadow-sm transition-all cursor-pointer whitespace-nowrap"
                    onClick={() => navigate('/today')}
                    type="button"
                  >
                    <span>开始当前任务</span>
                    <span className="material-symbols-outlined text-[18px]">arrow_forward</span>
                  </button>
                  <p className="text-[11px] text-center text-on-ink-variant leading-relaxed">完成后，系统会根据新的作答证据更新学习路径。</p>
                </div>
              </div>
            </aside>
          </div>

          {/* Agent 决策依据（五步） */}
          <details className="group rounded-xl border border-outline-border bg-white shadow-xs overflow-hidden" id="rationale-details">
            <summary className="p-3.5 text-xs md:text-sm font-bold text-on-surface cursor-pointer select-none flex items-center justify-between hover:bg-surface-subtle transition-colors border-b border-outline-border/40">
              <div className="flex items-center gap-2 text-primary-container">
                <span className="material-symbols-outlined text-[18px]">psychology</span>
                <span>为什么这样安排？（Agent 决策依据）</span>
              </div>
              <div className="flex items-center gap-2 text-xs font-normal text-on-ink-variant">
                <span className="hidden sm:inline">{decision?.reason || '查看候选集合与选择理由'}</span>
                <span className="font-medium text-primary-container flex items-center gap-0.5">详细依据 <span className="material-symbols-outlined text-[16px] group-open:rotate-180 transition-transform">expand_more</span></span>
              </div>
            </summary>
            <div className="p-4 md:p-5 flex flex-col gap-3.5 text-xs text-on-ink-variant bg-white">
              <div className="grid grid-cols-1 md:grid-cols-5 gap-3">
                <div className="p-3 rounded-lg bg-surface-subtle border border-outline-border/60 flex flex-col gap-1">
                  <div className="font-bold text-on-surface flex items-center gap-1.5">
                    <span className="w-4 h-4 rounded-full bg-primary-light text-primary-container text-[10px] flex items-center justify-center font-bold">1</span>
                    <span>读取状态</span>
                  </div>
                  <p className="text-[11px] text-on-ink-variant leading-relaxed">
                    当前「{focusNode?.title}」{focusEstimate === null ? '尚未评估' : `掌握度 ${Math.round(focusEstimate * 100)}%`}，今日剩余 {remainingMinutes} 分钟，计划 v{path.plan?.version ?? 0}。
                  </p>
                </div>
                <div className="p-3 rounded-lg bg-surface-subtle border border-outline-border/60 flex flex-col gap-1">
                  <div className="font-bold text-on-surface flex items-center gap-1.5">
                    <span className="w-4 h-4 rounded-full bg-primary-light text-primary-container text-[10px] flex items-center justify-center font-bold">2</span>
                    <span>检查约束</span>
                  </div>
                  <p className="text-[11px] text-on-ink-variant leading-relaxed">
                    先修关系与每日预算在模型调用前后均校验；{lockedCount > 0 ? `${lockedCount} 个节点前置未掌握，保持锁定。` : '当前无锁定节点。'}
                  </p>
                </div>
                <div className="p-3 rounded-lg bg-surface-subtle border border-outline-border/60 flex flex-col gap-1">
                  <div className="font-bold text-on-surface flex items-center gap-1.5">
                    <span className="w-4 h-4 rounded-full bg-primary-light text-primary-container text-[10px] flex items-center justify-center font-bold">3</span>
                    <span>比较动作</span>
                  </div>
                  <p className="text-[11px] text-on-ink-variant leading-relaxed">
                    规则层候选：{(decision?.candidate_actions ?? []).map((c) => c.label || c.action).join('；') || '暂无候选'}。
                  </p>
                </div>
                <div className="p-3 rounded-lg bg-primary-light/40 border border-primary-container/30 flex flex-col gap-1">
                  <div className="font-bold text-primary-container flex items-center gap-1.5">
                    <span className="w-4 h-4 rounded-full bg-primary-container text-white text-[10px] flex items-center justify-center font-bold">4</span>
                    <span>选择行动</span>
                  </div>
                  <p className="text-[11px] text-on-ink-variant leading-relaxed">
                    {(decision?.selected_action.label || decision?.reason || '保持当前计划')}
                    {decision && decision.planner_source !== 'llm' ? '（模型不可用，规则回退）' : ''}。
                  </p>
                </div>
                <div className="p-3 rounded-lg bg-surface-subtle border border-outline-border/60 flex flex-col gap-1">
                  <div className="font-bold text-on-surface flex items-center gap-1.5">
                    <span className="w-4 h-4 rounded-full bg-primary-light text-primary-container text-[10px] flex items-center justify-center font-bold">5</span>
                    <span>预期结果</span>
                  </div>
                  <p className="text-[11px] text-on-ink-variant leading-relaxed">完成后根据独立作答表现更新掌握证据，路径仅在任务集合真实变化时升版。</p>
                </div>
              </div>
            </div>
          </details>
        </div>
      </div>
    </div>
  );
}
