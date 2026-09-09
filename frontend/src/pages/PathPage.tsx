/** 当前路径：stitch _1 原版移植（调整说明短卡 + 先修因果链路 + 节点详情工作面板）。
 *  页面标题、当前节点、右侧节点详情均来自同一份 GET /goals/{id}/path 数据。
 *  学生侧不展示 plan_version / policy_version / reason_code / event_type 等内部字段。 */
import { useCallback, useEffect, useState } from 'react';

import { ApiError } from '../api/client';
import { getOverview, getPath, replanGoal } from '../api/endpoints';
import type { MasteryEntry, PathData, PathNode, RecentEvidence } from '../api/types';
import { navigate } from '../lib/router';

/** 隐藏内部枚举码（如 needs_support），仅保留学生可读文本 */
function cleanReason(text: string | null | undefined): string {
  return (text ?? '').replace(/[（(][A-Za-z_]+[)）]/g, '').replace(/；$/, '').trim();
}

function relTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  if (diff < 60_000) return '刚刚';
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}分钟前`;
  const d = new Date(iso);
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  if (d.toDateString() === yesterday.toDateString()) {
    return `昨天 ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  }
  return `${d.getMonth() + 1}月${d.getDate()}日`;
}

/** 从锁定原因「前置未掌握：A、B」解析前置节点名 */
function lockPreTitles(reason: string): string[] {
  return reason.startsWith('前置未掌握：') ? reason.slice('前置未掌握：'.length).split('、') : [];
}

const TASK_LABEL: Record<string, string> = {
  lesson: '讲解',
  practice: '独立练习',
  review: '复习验证',
};

export function PathPage() {
  const [path, setPath] = useState<PathData | null>(null);
  const [mastery, setMastery] = useState<MasteryEntry[]>([]);
  const [goalId, setGoalId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [replanning, setReplanning] = useState(false);
  const [replanMsg, setReplanMsg] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [tab, setTab] = useState<'adjusted' | 'stable'>('adjusted');
  const [cardOpen, setCardOpen] = useState(true);
  const [practiceOpen, setPracticeOpen] = useState(false);
  const [recentEvidence, setRecentEvidence] = useState<RecentEvidence[]>([]);

  const load = useCallback(async () => {
    try {
      const overview = await getOverview();
      const entry = overview.goals[0];
      if (!entry) { navigate('/'); return; }
      setGoalId(entry.goal.id);
      setMastery(entry.mastery);
      setRecentEvidence(overview.recent_evidence);
      const data = await getPath(entry.goal.id);
      setPath(data);
      setTab(data.previous_plan || data.stale ? 'adjusted' : 'stable');
      const byId = new Map(data.nodes.map((n) => [n.concept_id, n]));
      const ordered = data.plan
        ? data.plan.ordered_concept_ids.map((cid) => byId.get(cid)).filter((n): n is PathNode => Boolean(n))
        : data.nodes;
      const working = ordered.find((n) => n.status !== 'mastered' && n.status !== 'locked' && n.eligible);
      setSelected(working?.concept_id ?? ordered[0]?.concept_id ?? null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '加载路径失败');
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function replan() {
    if (!path?.plan || !goalId) return;
    setReplanning(true); setReplanMsg(null);
    try {
      const r = await replanGoal(goalId, 'student_request', path.plan.version);
      setReplanMsg(r.changed ? '已按最新学情更新路径。' : '路径无变化，保持当前安排。');
      await load();
    } catch (e) {
      setReplanMsg(e instanceof ApiError ? e.message : '重算失败，请稍后再试');
    } finally {
      setReplanning(false);
    }
  }

  if (error) {
    return (
      <div className="pl-64"><main className="w-full pt-16 min-h-screen bg-surface-bg">
        <div className="px-4 md:px-8 py-8"><div className="p-3.5 rounded-xl bg-error-container text-on-error-container text-sm">{error}</div></div>
      </main></div>
    );
  }
  if (!path) {
    return (
      <div className="pl-64">
        <main className="min-h-screen bg-surface-bg pt-16">
          <div className="loading-ring py-space-xl text-center text-on-surface-variant text-sm">正在加载路径…</div>
        </main>
      </div>
    );
  }
  if (!path.plan) {
    return (
      <div className="pl-64">
        <main className="min-h-screen bg-surface-bg pt-16">
          <div className="max-w-[720px] mx-auto px-4 md:px-8 py-8">
            <div className="p-5 rounded-xl bg-white border border-outline-border shadow-xs text-center flex flex-col gap-3 items-center">
              <div className="w-12 h-12 rounded-full bg-surface-subtle text-primary flex items-center justify-center">
                <span className="material-symbols-outlined text-[24px]">route</span>
              </div>
              <h2 className="text-lg font-bold text-on-surface font-serif">路径正在准备中</h2>
              <p className="text-xs text-on-surface-variant leading-relaxed">完成首轮诊断后，这里会展示你的专属研习路径。</p>
              <button className="px-3 py-1.5 rounded-md bg-primary hover:bg-primary-hover text-white text-xs font-medium shadow-xs" onClick={() => navigate('/profile/diagnosis')} type="button">
                去诊断
              </button>
            </div>
          </div>
        </main>
      </div>
    );
  }

  // ---------- 同一份 path 数据：顺序、当前节点、详情面板全部由此派生 ----------
  const plan = path.plan;
  const byId = new Map(path.nodes.map((n) => [n.concept_id, n]));
  const ordered = plan.ordered_concept_ids.map((cid) => byId.get(cid)).filter((n): n is PathNode => Boolean(n));
  const working = ordered.find((n) => n.status !== 'mastered' && n.status !== 'locked' && n.eligible) ?? null;
  const firstLocked = ordered.find((n) => n.status === 'locked') ?? null;
  const masteryOf = (cid: string) => mastery.find((m) => m.concept_id === cid);
  const selectedNode = ordered.find((n) => n.concept_id === selected) ?? working ?? ordered[0] ?? null;
  const selectedIdx = selectedNode ? ordered.findIndex((n) => n.concept_id === selectedNode.concept_id) : -1;
  const titleOf = (cid: string) => byId.get(cid)?.title ?? masteryOf(cid)?.title ?? cid;
  /** 锁定原因里的前置可能存的是概念 ID（如 C01），统一转成学生可读标题 */
  const preTitlesOf = (node: PathNode): string[] =>
    lockPreTitles(node.reason).map((t) => byId.get(t)?.title ?? masteryOf(t)?.title ?? t);

  const verb = working
    ? working.status === 'review_due' ? '复习' : working.status === 'unassessed' ? '补测' : '攻坚'
    : null;
  const headerTitle = working
    ? `下一步是什么：${verb}【${working.title}】`
    : '下一步是什么：巩固已掌握的节点';

  // 微调对比（仅用可读概念标题，不展示版本号与原因码）
  const prevIds = path.previous_plan?.ordered_concept_ids ?? null;
  const curIds = plan.ordered_concept_ids;
  const added = prevIds ? curIds.filter((cid) => !prevIds.includes(cid)) : [];
  const removed = prevIds ? prevIds.filter((cid) => !curIds.includes(cid)) : [];
  const firstDiffIdx = prevIds ? curIds.findIndex((cid, i) => prevIds[i] !== cid) : -1;
  const changedCid = added[0] ?? removed[0] ?? (firstDiffIdx >= 0 ? curIds[firstDiffIdx] : null) ?? working?.concept_id ?? null;
  const adjustHeadline = !prevIds
    ? `当前路径依据首轮诊断生成：先攻克【${working?.title ?? titleOf(curIds[0] ?? '')}】`
    : added.length > 0
      ? `路径有微调：新增「${added.map(titleOf).join('、')}」`
      : removed.length > 0
        ? `路径有微调：移除「${removed.map(titleOf).join('、')}」`
        : `路径有微调：「${changedCid ? titleOf(changedCid) : ''}」的研习顺序有调整`;
  const adjustExplain = cleanReason(changedCid ? byId.get(changedCid)?.reason : null)
    || '依据近期作答证据重新排序，已完成任务保持不变。';
  const relatedTaskPairs = ordered
    .filter((n) => n.concept_id === changedCid)
    .flatMap((n) => n.tasks.map((t) => ({ node: n, task: t })))
    .filter(({ task }) => task.status === 'queued' || task.status === 'active');

  const nodeStatusPill = (node: PathNode, focus: boolean): { text: string; cls: string } => {
    const m = masteryOf(node.concept_id);
    const pct = m && m.estimate !== null ? Math.round(m.estimate * 100) : null;
    if (node.status === 'locked') {
      const pres = preTitlesOf(node);
      return {
        text: pres.length > 0 ? `待解锁（需先完成 ${pres.join(' 与 ')}）` : '待解锁',
        cls: 'bg-surface-subtle text-status-locked border border-outline-border',
      };
    }
    if (node.status === 'mastered') {
      return { text: pct !== null ? `已掌握 · ${pct}%` : '已掌握', cls: 'bg-status-mastered-bg text-status-mastered' };
    }
    if (focus) {
      return { text: pct !== null ? `攻坚中 · ${pct}%` : '攻坚中', cls: 'bg-primary text-white' };
    }
    if (node.status === 'unassessed') {
      return { text: '可开始 · 尚未评估', cls: 'bg-surface-subtle text-on-surface-variant' };
    }
    return { text: pct !== null ? `需复习 · ${pct}%` : '需复习', cls: 'bg-secondary-light text-secondary-dark border border-secondary-border' };
  };

  return (
    <div className="pl-64">
      <main className="max-w-[1440px] mx-auto px-4 md:px-8 py-7 flex-1 w-full flex flex-col gap-5 pt-20 bg-surface-bg min-h-screen">

        {/* 标题与推荐原因（stitch _1 原版） */}
        <header className="flex flex-col md:flex-row md:items-end justify-between gap-4 pb-2 border-b border-outline-border/60">
          <div className="flex flex-col gap-1">
            <h1 className="text-2xl md:text-[26px] font-bold tracking-tight text-on-surface font-serif flex items-center gap-2">
              <span>{headerTitle}</span>
            </h1>
            <div className="flex items-center flex-wrap gap-2 text-xs md:text-sm text-on-surface-variant">
              <span className="font-medium text-on-surface">
                目标：{working ? `「${working.title}」等 ${ordered.length} 个知识点` : `共 ${ordered.length} 个知识点`}
              </span>
              <span className="text-outline-dim">·</span>
              <span className="text-primary font-medium">{cleanReason(working?.reason) || '按前置顺序平稳推进。'}</span>
            </div>
          </div>
          <div className="flex items-center gap-2 self-start md:self-auto shrink-0">
            <button
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white border border-outline-border text-on-surface hover:bg-surface-subtle text-xs font-medium transition-all shadow-xs"
              onClick={() => setCardOpen((v) => !v)} type="button"
            >
              <span className="material-symbols-outlined text-[16px] text-primary">{cardOpen ? 'expand_less' : 'expand_more'}</span>
              <span>{cardOpen ? '收起调整说明' : '展开调整说明'}</span>
            </button>
          </div>
        </header>

        {replanMsg && (
          <div className="p-3 rounded-lg bg-primary-light border border-primary/20 text-xs text-on-surface font-medium">{replanMsg}</div>
        )}

        {/* 路径调整面板（stitch _1 短卡双模式） */}
        {cardOpen && (
          <section className="rounded-xl bg-white border border-outline-border shadow-xs overflow-hidden transition-all duration-200">
            <div className="p-4 md:p-5 flex flex-col gap-3">
              <div className="flex items-center justify-between gap-2 pb-2.5 border-b border-surface-subtle">
                <div className="flex items-center gap-1.5 p-1 bg-surface-subtle rounded-lg">
                  <button
                    className={`px-2.5 py-1 rounded text-xs flex items-center gap-1.5 transition-all ${tab === 'adjusted' ? 'font-semibold bg-white text-primary shadow-xs' : 'font-medium text-on-surface-variant hover:text-on-surface'}`}
                    onClick={() => setTab('adjusted')} type="button"
                  >
                    <span className="w-2 h-2 rounded-full bg-secondary-accent" />
                    <span>路径有微调</span>
                  </button>
                  <button
                    className={`px-2.5 py-1 rounded text-xs flex items-center gap-1.5 transition-all ${tab === 'stable' ? 'font-semibold bg-white text-primary shadow-xs' : 'font-medium text-on-surface-variant hover:text-on-surface'}`}
                    onClick={() => setTab('stable')} type="button"
                  >
                    <span className="w-1.5 h-1.5 rounded-full bg-status-mastered" />
                    <span>路径保持不变（平稳状态）</span>
                  </button>
                </div>
                <span className="text-xs text-on-surface-variant hidden sm:inline">依据近期错因轻量优化</span>
              </div>

              {tab === 'adjusted' ? (
                <div className="flex flex-col gap-2.5">
                  <div className="p-3.5 rounded-lg bg-secondary-light/70 border border-secondary-border flex flex-col md:flex-row items-start md:items-center justify-between gap-3">
                    <div className="flex items-start gap-3">
                      <div className="w-7 h-7 rounded-full bg-white text-secondary-accent border border-secondary-border flex items-center justify-center shrink-0 mt-0.5 shadow-xs">
                        <span className="material-symbols-outlined text-[16px]">tune</span>
                      </div>
                      <div className="flex flex-col gap-1">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-xs md:text-sm font-bold text-secondary-dark">{adjustHeadline}</span>
                        </div>
                        <p className="text-xs text-on-surface-variant leading-relaxed">{adjustExplain}</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 shrink-0 self-end md:self-auto">
                      {relatedTaskPairs.length > 0 && (
                        <button
                          className="px-3 py-1.5 rounded-md bg-white hover:bg-surface-subtle text-on-surface text-xs font-medium border border-outline-border transition-colors shadow-xs"
                          onClick={() => setPracticeOpen((v) => !v)} type="button"
                        >
                          查看相关练习 ({relatedTaskPairs.length}题)
                        </button>
                      )}
                      <button
                        className="px-3 py-1.5 rounded-md bg-primary hover:bg-primary-hover text-white text-xs font-medium transition-colors shadow-xs"
                        onClick={replan} disabled={replanning} type="button"
                      >
                        {replanning ? '更新中…' : '按此微调推进'}
                      </button>
                    </div>
                  </div>
                  {practiceOpen && relatedTaskPairs.length > 0 && (
                    <div className="p-3 rounded-lg bg-surface-subtle text-xs text-on-surface-variant border border-outline-border flex flex-col gap-2">
                      <div className="font-semibold text-on-surface flex items-center gap-1.5">
                        <span className="material-symbols-outlined text-[15px] text-primary">menu_book</span>
                        <span>关联练习题 ({relatedTaskPairs.length} 题)</span>
                      </div>
                      <div className="flex flex-col gap-1.5 pl-2 text-xs">
                        {relatedTaskPairs.map(({ node, task }, i) => (
                          <div key={task.id}>
                            {i + 1}. <span className="text-on-surface font-medium">{node.title}</span>
                            {' '}{TASK_LABEL[task.type] ?? '练习'}（{task.estimated_minutes} 分钟）
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <div className="p-3.5 rounded-lg bg-surface-subtle border border-outline-border flex items-center justify-between">
                  <div className="flex items-center gap-2 text-xs text-on-surface">
                    <span className="material-symbols-outlined text-status-mastered text-[18px]">verified</span>
                    <span className="font-medium">路径保持不变 · 节奏平稳有序推进</span>
                  </div>
                  {path.previous_plan && (
                    <button className="text-xs text-primary font-medium hover:underline" onClick={() => setTab('adjusted')} type="button">
                      查看微调版本
                    </button>
                  )}
                </div>
              )}
            </div>
          </section>
        )}

        {/* 主工作区：左因果链路 7 列 + 右节点详情 5 列 */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
          <section className="lg:col-span-7 flex flex-col gap-3">
            <div className="flex items-center justify-between gap-2 px-1">
              <h2 className="text-sm font-bold text-on-surface flex items-center gap-1.5">
                <span className="material-symbols-outlined text-primary text-[18px]">schema</span>
                <span>先修因果链路图</span>
              </h2>
              <div className="flex items-center gap-3 text-xs text-on-surface-variant">
                <span className="inline-flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-status-mastered" />已掌握</span>
                <span className="inline-flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-secondary-accent" />需复习</span>
                <span className="inline-flex items-center gap-1 text-primary font-medium"><span className="w-2 h-2 rounded-full bg-primary" />攻坚中</span>
                <span className="inline-flex items-center gap-1 text-status-locked"><span className="material-symbols-outlined text-[13px]">lock</span>待解锁</span>
              </div>
            </div>

            <div className="p-4 md:p-5 rounded-xl bg-white border border-outline-border shadow-xs flex flex-col">
              {ordered.map((node, i) => {
                const focus = working?.concept_id === node.concept_id;
                const m = masteryOf(node.concept_id);
                const evidence = m?.evidence_count ?? 0;
                const pending = node.tasks.filter((t) => t.status !== 'completed');
                const pendingMinutes = pending.reduce((s, t) => s + t.estimated_minutes, 0);
                const pill = nodeStatusPill(node, focus);
                const isLast = i === ordered.length - 1;
                const locked = node.status === 'locked';
                const icon = locked
                  ? 'lock'
                  : node.status === 'mastered'
                    ? 'check'
                    : node.status === 'needs_support' || node.status === 'review_due'
                      ? 'sync'
                      : focus ? 'play_arrow' : 'remove';
                const circleCls = locked
                  ? 'bg-white text-status-locked border border-outline-border'
                  : node.status === 'mastered'
                    ? 'bg-status-mastered-bg text-status-mastered border border-status-mastered/30'
                    : node.status === 'needs_support' || node.status === 'review_due'
                      ? 'bg-secondary-light text-secondary-accent border border-secondary-border'
                      : focus
                        ? 'bg-primary text-white'
                        : 'bg-surface-subtle text-on-surface-variant border border-outline-border';
                const rowCls = locked
                  ? 'bg-surface-subtle/50 hover:bg-surface-subtle border border-outline-border'
                  : focus
                    ? 'bg-primary-light/40 border-2 border-primary shadow-xs'
                    : node.status === 'needs_support' || node.status === 'review_due'
                      ? 'bg-secondary-light/40 hover:bg-secondary-light/70 border border-secondary-border/60'
                      : 'bg-surface-subtle/70 hover:bg-surface-subtle border border-transparent hover:border-outline-border';
                return (
                  <div key={node.concept_id}>
                    {locked && lockPreTitles(node.reason).length > 1 && (
                      <div className="relative pl-6 pb-2 text-xs text-status-locked flex items-center gap-1.5">
                        <span className="material-symbols-outlined text-[16px]">call_merge</span>
                        <span>
                          汇聚：完成 {preTitlesOf(node).join(' 与 ')} 后解锁「{node.title}」
                        </span>
                      </div>
                    )}
                    <div
                      className={`relative flex ${focus ? 'items-center' : 'items-start'} gap-3.5 ${isLast ? '' : 'pb-4'} group cursor-pointer`}
                      onClick={() => setSelected(node.concept_id)}
                    >
                      {!isLast && <div className="absolute left-3.5 top-7 bottom-0 w-0.5 bg-outline-border" />}
                      <div className={`relative z-10 w-7 h-7 rounded-full flex items-center justify-center shrink-0 ${circleCls}`}>
                        <span className="material-symbols-outlined text-[16px]">{icon}</span>
                      </div>
                      <div className={`flex-1 p-3 rounded-lg flex items-center justify-between gap-3 transition-colors ${rowCls}`}>
                        <div className="flex items-center gap-2 text-xs flex-wrap">
                          <span className={`font-semibold text-sm ${focus ? 'text-primary' : 'text-on-surface'}`}>{i + 1}. {node.title}</span>
                          <span className={`px-2 py-0.5 rounded text-[11px] flex items-center gap-1 ${pill.cls}`}>
                            {locked && <span className="material-symbols-outlined text-[11px]">lock</span>}
                            {pill.text}
                          </span>
                          <span className="text-on-surface-variant">
                            {evidence} 条证据{pendingMinutes > 0 ? ` · 预计 ${pendingMinutes} 分钟` : ''}
                          </span>
                        </div>
                        <span className={`material-symbols-outlined text-[18px] ${focus ? 'text-primary' : locked ? 'text-status-locked' : 'text-outline-dim group-hover:text-primary'}`}>
                          {focus ? 'arrow_forward' : 'chevron_right'}
                        </span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          <aside className="lg:col-span-5 flex flex-col gap-3 lg:sticky lg:top-20">
            <div className="flex items-center justify-between px-1">
              <h2 className="text-sm font-bold text-on-surface flex items-center gap-1.5">
                <span className="material-symbols-outlined text-primary text-[18px]">info</span>
                <span>节点详情工作面板</span>
              </h2>
              <div className="flex items-center gap-1 bg-surface-subtle p-0.5 rounded-lg border border-outline-border">
                {working && (
                  <button
                    className={`px-2 py-0.5 rounded text-xs ${selected === working.concept_id ? 'font-semibold bg-white text-primary shadow-xs' : 'font-medium text-on-surface-variant hover:text-on-surface'}`}
                    onClick={() => setSelected(working.concept_id)} type="button"
                  >
                    {working.title} (当前)
                  </button>
                )}
                {firstLocked && (
                  <button
                    className={`px-2 py-0.5 rounded text-xs ${selected === firstLocked.concept_id ? 'font-semibold bg-white text-primary shadow-xs' : 'font-medium text-on-surface-variant hover:text-on-surface'}`}
                    onClick={() => setSelected(firstLocked.concept_id)} type="button"
                  >
                    {firstLocked.title} (待解锁)
                  </button>
                )}
              </div>
            </div>

            {selectedNode && (() => {
              const locked = selectedNode.status === 'locked';
              const m = masteryOf(selectedNode.concept_id);
              const pct = m && m.estimate !== null ? Math.round(m.estimate * 100) : null;
              const pending = selectedNode.tasks.filter((t) => t.status !== 'completed');
              const pendingMinutes = pending.reduce((s, t) => s + t.estimated_minutes, 0);
              const statusText = locked
                ? '待解锁'
                : selectedNode.status === 'mastered'
                  ? '已掌握'
                  : selectedNode.status === 'review_due'
                    ? '复习到期'
                    : selectedNode.status === 'unassessed'
                      ? '准备开始'
                      : '攻坚中';
              const pres = preTitlesOf(selectedNode);
              const priorNodes = selectedIdx > 0 ? ordered.slice(Math.max(0, selectedIdx - 3), selectedIdx) : [];
              const recentForNode = recentEvidence.filter((e) => e.concept_id === selectedNode.concept_id).slice(0, 2);
              return (
                <div className="p-5 rounded-xl bg-white border border-outline-border shadow-xs flex flex-col gap-4">
                  <div className="flex items-start justify-between pb-3 border-b border-surface-subtle">
                    <div className="flex flex-col gap-0.5">
                      <span className={`text-xs font-semibold ${locked ? 'text-status-locked' : 'text-primary'}`}>
                        第 {selectedIdx + 1} 步 · {statusText}
                      </span>
                      <h3 className="text-lg font-bold text-on-surface font-serif">{selectedNode.title}</h3>
                      <div className={`text-xs mt-0.5 flex items-center gap-2 ${locked ? 'text-status-locked' : 'text-on-surface-variant'}`}>
                        {pct !== null ? (
                          <>
                            <span>掌握度 <strong className={`font-semibold ${m?.status === 'needs_support' || m?.status === 'review_due' ? 'text-secondary-dark' : 'text-primary'}`}>{pct}%</strong></span>
                            <span className="text-outline-dim">·</span>
                          </>
                        ) : !locked && <><span>尚未评估</span><span className="text-outline-dim">·</span></>}
                        <span>{m?.evidence_count ?? 0} 条证据</span>
                      </div>
                    </div>
                    {pendingMinutes > 0 && (
                      <span className="px-2.5 py-1 rounded text-xs font-semibold bg-primary-light text-primary border border-primary/20 shrink-0">
                        预计 {pendingMinutes} 分钟
                      </span>
                    )}
                  </div>

                  {locked ? (
                    <div className="p-3 rounded-lg bg-surface-subtle border border-outline-border text-xs text-on-surface-variant flex items-center gap-2">
                      <span className="material-symbols-outlined text-[18px] text-status-locked shrink-0">lock</span>
                      <span>需先完成 {pres.join(' 与 ')} 后自动激活，以保持平稳学习梯度。</span>
                    </div>
                  ) : (
                    <div className="flex flex-col gap-1">
                      <span className="text-xs font-semibold text-on-surface-variant uppercase tracking-wider">本次研习目标</span>
                      <p className="text-xs md:text-sm text-on-surface leading-relaxed p-3 rounded-lg bg-surface-subtle border border-outline-border/60">
                        {cleanReason(selectedNode.reason) || '按当前学情安排，完成本节点后自动更新掌握证据。'}
                      </p>
                    </div>
                  )}

                  {locked ? (
                    pres.length > 0 && (
                      <div className="flex flex-col gap-1.5">
                        <span className="text-xs font-semibold text-on-surface-variant uppercase tracking-wider">解锁必备前置项</span>
                        <div className="flex flex-col gap-1.5 text-xs">
                          {pres.map((preTitle) => {
                            const preNode = ordered.find((n) => n.title === preTitle);
                            const preMastered = preNode?.status === 'mastered';
                            const preWorking = working?.concept_id === preNode?.concept_id;
                            return (
                              <div
                                className={`p-2 rounded-lg flex items-center justify-between ${preMastered ? 'bg-primary-light/40 border border-primary/20' : preWorking ? 'bg-secondary-light/80 border border-secondary-border/60' : 'bg-surface-subtle border border-outline-border/60'}`}
                                key={preTitle}
                              >
                                <span className={preMastered ? 'text-primary font-medium' : preWorking ? 'text-on-surface font-medium' : 'text-status-locked'}>{preTitle}</span>
                                <span className={preMastered ? 'text-primary' : preWorking ? 'text-secondary-dark' : 'text-status-locked'}>
                                  {preMastered ? '已掌握' : preWorking ? '学习中' : '未开始'}
                                </span>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )
                  ) : (
                    priorNodes.length > 0 && (
                      <div className="flex flex-col gap-1.5">
                        <span className="text-xs font-semibold text-on-surface-variant uppercase tracking-wider">前置知识掌握</span>
                        <div className="flex flex-col gap-1.5 text-xs">
                          {priorNodes.map((pre) => {
                            const preM = masteryOf(pre.concept_id);
                            const prePct = preM && preM.estimate !== null ? Math.round(preM.estimate * 100) : null;
                            const preWeak = pre.status === 'needs_support' || pre.status === 'review_due';
                            return (
                              <div className={`p-2 rounded-lg flex items-center justify-between ${preWeak ? 'bg-secondary-light/80 border border-secondary-border/60' : 'bg-surface-subtle border border-outline-border/40'}`} key={pre.concept_id}>
                                <span className="text-on-surface flex items-center gap-1.5">
                                  <span className={`material-symbols-outlined text-[15px] ${preWeak ? 'text-secondary-accent' : 'text-status-mastered'}`}>
                                    {preWeak ? 'sync' : 'check_circle'}
                                  </span>
                                  {pre.title}
                                </span>
                                <span className={`font-medium ${preWeak ? 'text-secondary-dark' : 'text-status-mastered'}`}>
                                  {pre.status === 'mastered' ? '已掌握' : preWeak ? '需复习' : '尚未评估'}{prePct !== null ? ` · ${prePct}%` : ''}
                                </span>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )
                  )}

                  <details className="group rounded-lg border border-outline-border overflow-hidden bg-surface-subtle/60">
                    <summary className="p-2.5 text-xs font-medium text-on-surface cursor-pointer select-none flex items-center justify-between hover:bg-surface-subtle transition-colors">
                      <span className="flex items-center gap-1.5 text-primary">
                        <span className="material-symbols-outlined text-[16px]">history_edu</span>
                        <span>查看近期答题证据与推荐依据</span>
                      </span>
                      <span className="material-symbols-outlined text-[16px] text-outline-dim group-open:rotate-180 transition-transform">expand_more</span>
                    </summary>
                    <div className="p-3 pt-2 text-xs text-on-surface-variant border-t border-outline-border/60 flex flex-col gap-2 bg-white">
                      <div>
                        <div className="font-semibold text-on-surface mb-0.5">作答痕迹：</div>
                        {recentForNode.length === 0 ? (
                          <p>暂无近期作答记录。</p>
                        ) : (
                          recentForNode.map((e) => (
                            <p key={e.id}>
                              {relTime(e.created_at)} · {e.eligible ? '独立作答，计入掌握证据' : '辅助作答，不计入证据'}
                            </p>
                          ))
                        )}
                      </div>
                      <div>
                        <div className="font-semibold text-on-surface mb-0.5">推荐依据：</div>
                        <p>{cleanReason(selectedNode.reason) || '按前置顺序与当前学情综合安排。'}</p>
                      </div>
                    </div>
                  </details>

                  <div className="flex flex-col gap-2 pt-2">
                    {locked ? (
                      <button
                        className="w-full py-2.5 px-4 rounded-lg bg-primary hover:bg-primary-hover text-white text-sm font-semibold flex items-center justify-center gap-1.5 shadow-sm transition-all"
                        onClick={() => working && setSelected(working.concept_id)} type="button"
                      >
                        <span>返回当前攻坚：{working?.title ?? ''}</span>
                        <span className="material-symbols-outlined text-[18px]">arrow_back</span>
                      </button>
                    ) : (
                      <>
                        <button
                          className="w-full py-2.5 px-4 rounded-lg bg-primary hover:bg-primary-hover text-white text-sm font-semibold flex items-center justify-center gap-1.5 shadow-sm transition-all"
                          onClick={() => navigate('/today')} type="button"
                        >
                          <span>继续学习这个节点</span>
                          <span className="material-symbols-outlined text-[18px]">arrow_forward</span>
                        </button>
                        <button
                          className="w-full py-1.5 px-3 rounded-lg text-xs font-medium text-on-surface-variant hover:text-on-surface text-center transition-colors"
                          onClick={() => navigate('/records/mastery')} type="button"
                        >
                          查看知识要点
                        </button>
                      </>
                    )}
                  </div>
                </div>
              );
            })()}
          </aside>
        </div>

        {/* 页脚（stitch _1 原版：纯净极简） */}
        <footer className="w-full border-t border-outline-border/60 bg-white/70 py-3 mt-6 rounded-lg">
          <div className="px-2 flex flex-col sm:flex-row items-center justify-between gap-2 text-xs text-on-surface-variant">
            <div className="flex items-center gap-1.5">
              <span className="material-symbols-outlined text-primary text-[16px]">verified</span>
              <span>坚持因果拓扑与先修递进，每一步皆有依据</span>
            </div>
            <span className="text-outline-dim sm:inline hidden">自适应平稳保护已开启</span>
          </div>
        </footer>
      </main>
    </div>
  );
}
