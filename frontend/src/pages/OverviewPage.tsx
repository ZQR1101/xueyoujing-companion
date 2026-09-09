/** 我的学情：stitch _2 原版移植（布局与文字密度对齐 zip 版）。
 *  全部按真实状态渲染：未诊断→开始诊断；已诊断未开始→开始任务/查看路径；
 *  有未完成任务→继续学习；无今日任务→等待规划/去诊断。
 *  数据来自 GET /me/overview 与 GET /goals/{id}/path 同源节点，不显示内部字段。 */
import { useCallback, useEffect, useState } from 'react';

import { ApiError } from '../api/client';
import { createGoal, getOverview, getPath } from '../api/endpoints';
import type { MasteryEntry, OverviewData, PathData, PathNode } from '../api/types';
import { navigate } from '../lib/router';

/** 隐藏内部枚举码（如 needs_support），仅保留学生可读文本 */
function cleanReason(text: string | null | undefined): string {
  return (text ?? '').replace(/[（(][A-Za-z_]+[)）]/g, '').replace(/；$/, '').trim();
}

function conceptTitleOf(mastery: MasteryEntry[], cid: string): string {
  return mastery.find((m) => m.concept_id === cid)?.title ?? cid;
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

function shortDate(iso: string): string {
  const d = new Date(iso);
  return `${d.getMonth() + 1}月${d.getDate()}日`;
}

const EXCLUSION_TEXT: Record<string, string> = {
  not_first_attempt: '重复作答',
  hint_used: '提示辅导',
  solution_seen: '已看解析',
  family_already_counted: '同类题已计数',
};

const TASK_CHIP: Record<string, string> = {
  lesson: '知识讲解',
  practice: '单题检验',
  review: '复习检验',
};

const TASK_SUFFIX: Record<string, string> = {
  lesson: '讲解学习',
  practice: '独立练习',
  review: '复习验证',
};

export function OverviewPage() {
  const [overview, setOverview] = useState<OverviewData | null>(null);
  const [path, setPath] = useState<PathData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    const data = await getOverview();
    setOverview(data);
    const entry = data.goals[0];
    if (entry) {
      try {
        setPath(await getPath(entry.goal.id));
      } catch { /* 路径缺失（如诊断未完成）不阻塞页面 */ }
    }
  }, []);

  useEffect(() => {
    load().catch((e: ApiError) => setError(e.message));
  }, [load]);

  async function startDiagnosis() {
    setCreating(true);
    try {
      await createGoal('quadratic', [], 25);
      navigate('/profile/diagnosis');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '创建目标失败');
      setCreating(false);
    }
  }

  if (error) {
    return (
      <div className="pl-64">
        <main className="w-full pt-16 min-h-screen bg-surface">
          <div className="max-w-[1140px] mx-auto px-gutter-desktop py-space-xl">
            <div className="p-space-md rounded-xl bg-error-container text-on-error-container font-body-md">{error}</div>
          </div>
        </main>
      </div>
    );
  }
  if (!overview) {
    return (
      <div className="pl-64">
        <main className="w-full pt-16 min-h-screen bg-surface">
          <div className="loading-ring p-space-xl text-center text-outline font-body-md">正在加载学情…</div>
        </main>
      </div>
    );
  }

  const entry = overview.goals[0];
  const student = overview.student;

  // ---------- 状态一：未诊断（无目标，stitch _2 冷启动卡原版） ----------
  if (!entry) {
    return (
      <div className="pl-64">
        <main className="w-full pt-16 bg-surface min-h-screen">
          <div className="flex flex-col w-full">
            <div className="w-full max-w-[1140px] mx-auto px-gutter-desktop py-space-xl flex flex-col gap-space-xl">
              <section className="bg-surface-container-lowest rounded-xl p-space-lg shadow-sm flex flex-col md:flex-row items-center justify-between gap-space-lg">
                <div className="flex flex-col gap-space-xs max-w-[680px]">
                  <h2 className="font-headline-md text-headline-md text-on-surface">
                    先用几道题，找到适合你的起点
                  </h2>
                  <p className="font-body-md text-body-md text-on-surface-variant">
                    3道自选题目 · 无倒计时 · 即刻生成起步
                  </p>
                </div>
                <button
                  className="px-space-xl py-space-sm rounded-lg bg-primary text-on-primary font-title-md text-title-md hover:bg-primary-container transition-all flex items-center gap-space-xs shrink-0 active:scale-[0.99] shadow-sm"
                  onClick={startDiagnosis}
                  disabled={creating}
                  type="button"
                >
                  <span>{creating ? '正在准备…' : '开始诊断'}</span>
                  <span className="material-symbols-outlined text-base">arrow_forward</span>
                </button>
              </section>
              <div className="flex items-center justify-between pt-space-md pb-space-lg text-outline">
                <span className="font-label-sm text-label-sm">
                  学有所径 · 随练随测客观学情
                </span>
                <span className="font-label-sm text-label-sm">初中数学</span>
              </div>
            </div>
          </div>
        </main>
      </div>
    );
  }

  // ---------- 数据态：与 path 同源的节点序列 ----------
  const mastery = entry.mastery;
  const total = mastery.length;
  const assessed = mastery.filter((m) => m.status !== 'unassessed').length;
  const masteredCount = mastery.filter((m) => m.status === 'mastered').length;
  const nodeById = new Map<string, PathNode>((path?.nodes ?? []).map((n) => [n.concept_id, n]));
  const orderedNodes = path?.plan
    ? path.plan.ordered_concept_ids.map((cid) => nodeById.get(cid)).filter((n): n is PathNode => Boolean(n))
    : path?.nodes ?? [];
  const workingNode = orderedNodes.find(
    (n) => n.status !== 'mastered' && n.status !== 'locked' && n.eligible,
  ) ?? null;
  const pendingTaskPairs = orderedNodes
    .flatMap((n) => n.tasks.map((t) => ({ node: n, task: t })))
    .filter(({ task }) => task.status === 'queued' || task.status === 'active');
  const nextPair = pendingTaskPairs.find((p) => p.task.status === 'active') ?? pendingTaskPairs[0] ?? null;
  const pendingMinutes = pendingTaskPairs.reduce((s, p) => s + p.task.estimated_minutes, 0);
  const hasWork = pendingTaskPairs.length > 0;
  const started = orderedNodes
    .flatMap((n) => n.tasks)
    .some((t) => t.status === 'completed' || t.status === 'active');
  const titleOf = (cid: string) => conceptTitleOf(mastery, cid);

  const headline = hasWork
    ? started
      ? '今天，从上次的进度继续。'
      : '路径已就绪，从第一个任务开始。'
    : '今天的任务已完成，等待下一轮规划。';

  return (
    <div className="pl-64">
      <main className="w-full pt-16 bg-surface min-h-screen">
        <div className="flex flex-col w-full">
          <div className="w-full max-w-[1140px] mx-auto px-gutter-desktop py-space-xl flex flex-col gap-space-xl">

            {/* 顶部行动与目标条（stitch _2 原版） */}
            <section className="bg-surface-container-lowest rounded-xl p-space-lg shadow-sm flex flex-col gap-space-md">
              <div className="flex flex-col md:flex-row md:items-center justify-between gap-space-md">
                <div className="flex flex-col gap-space-2xs">
                  <div className="flex items-center gap-space-xs text-outline">
                    <span className="font-label-sm text-label-sm uppercase tracking-wider">初中数学</span>
                    <span className="w-1.5 h-1.5 rounded-full bg-primary" />
                    <span className="font-label-sm text-label-sm text-primary">自适应阶段</span>
                  </div>
                  <h1 className="font-headline-lg text-headline-lg text-on-surface font-semibold tracking-tight">
                    {headline}
                  </h1>
                </div>
                <div className="flex items-center gap-space-sm shrink-0">
                  {hasWork ? (
                    <>
                      {!started && (
                        <button
                          className="inline-flex items-center gap-space-xs px-space-md py-space-sm rounded-lg bg-surface-container-lowest text-primary font-title-md text-title-md border border-outline-variant/60 hover:bg-surface-container-low transition-all active:scale-[0.99] shadow-sm"
                          onClick={() => navigate('/path')} type="button"
                        >
                          <span>查看路径</span>
                        </button>
                      )}
                      <button
                        className="inline-flex items-center gap-space-xs px-space-lg py-space-sm rounded-lg bg-primary text-on-primary font-title-md text-title-md hover:bg-primary-container transition-all active:scale-[0.99] shadow-sm"
                        onClick={() => navigate('/today')} type="button"
                      >
                        <span>{started ? '继续学习' : '开始任务'}</span>
                        <span className="material-symbols-outlined text-lg">arrow_forward</span>
                      </button>
                    </>
                  ) : (
                    <button
                      className="inline-flex items-center gap-space-xs px-space-lg py-space-sm rounded-lg bg-primary text-on-primary font-title-md text-title-md hover:bg-primary-container transition-all active:scale-[0.99] shadow-sm"
                      onClick={() => navigate('/profile/diagnosis')} type="button"
                    >
                      <span>去诊断</span>
                      <span className="material-symbols-outlined text-lg">arrow_forward</span>
                    </button>
                  )}
                </div>
              </div>
              <div className="flex flex-wrap items-center justify-between gap-space-sm pt-space-xs border-t border-surface-variant/40">
                <div className="flex flex-wrap items-center gap-x-space-md gap-y-space-2xs font-body-md text-body-md">
                  <div className="flex items-center gap-space-2xs">
                    <span className="text-outline font-label-md text-label-md">当前目标：</span>
                    <span className="font-title-md text-title-md text-on-surface font-medium">
                      {workingNode ? `「${workingNode.title}」等 ${total} 个知识点` : `共 ${total} 个知识点`}
                    </span>
                  </div>
                  <span className="text-outline-variant hidden sm:inline">|</span>
                  <div className="flex items-center gap-space-2xs">
                    <span className="text-outline font-label-md text-label-md">今日计划：</span>
                    <span className="font-medium text-on-surface">
                      {hasWork ? `${pendingMinutes} 分钟` : `${student.daily_minutes} 分钟`}
                    </span>
                  </div>
                </div>
                <div className="flex items-center gap-space-xs">
                  <span className="px-space-sm py-0.5 rounded-full bg-surface-container font-label-sm text-label-sm text-on-surface-variant">
                    已评估 <strong className="text-on-surface font-semibold">{assessed}</strong> / {total}
                  </span>
                  <span className="px-space-sm py-0.5 rounded-full bg-primary-fixed font-label-sm text-label-sm text-on-primary-fixed">
                    已掌握 <strong className="text-primary font-semibold">{masteredCount}</strong> / {total}
                  </span>
                </div>
              </div>
            </section>

            {/* 主双栏工作区（stitch _2 原版 8 + 4 列） */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-space-xl items-start">
              {/* 左栏 */}
              <div className="lg:col-span-8 flex flex-col gap-space-xl min-w-0">
                {hasWork && nextPair && (
                  <article className="bg-surface-container-lowest rounded-xl p-space-lg shadow-sm relative overflow-hidden flex flex-col gap-space-md">
                    <div className="flex items-start justify-between gap-space-sm">
                      <div className="flex flex-col gap-space-2xs">
                        <div className="flex items-center gap-space-xs">
                          <span className="px-space-xs py-0.5 rounded-full bg-primary-fixed text-on-primary-fixed font-label-sm text-label-sm font-medium">
                            预计 {nextPair.task.estimated_minutes} 分钟
                          </span>
                          <span className="px-space-xs py-0.5 rounded-full bg-surface-container text-on-surface-variant font-label-sm text-label-sm">
                            {TASK_CHIP[nextPair.task.type] ?? '研习任务'}
                          </span>
                        </div>
                        <h2 className="font-headline-md text-headline-md text-on-surface mt-1">
                          {titleOf(nextPair.node.concept_id)}{TASK_SUFFIX[nextPair.task.type] ?? ''}
                        </h2>
                      </div>
                      <div className="w-10 h-10 rounded-lg bg-surface-container flex items-center justify-center text-primary shrink-0">
                        <span className="material-symbols-outlined">quiz</span>
                      </div>
                    </div>
                    <div className="bg-surface-container-low border border-outline-variant/40 rounded-xl p-space-sm flex flex-col gap-1.5">
                      <div className="flex items-center justify-between gap-space-xs">
                        <div className="flex items-center gap-space-2xs text-primary font-title-md text-title-md font-medium">
                          <span className="material-symbols-outlined text-base">psychology</span>
                          <span>安排依据</span>
                        </div>
                        <details className="text-right">
                          <summary className="cursor-pointer text-outline hover:text-primary font-label-sm text-label-sm select-none list-none inline-flex items-center gap-0.5">
                            <span>查看依据</span>
                            <span className="material-symbols-outlined text-sm">expand_more</span>
                          </summary>
                          <p className="text-left font-body-sm text-body-sm text-on-surface-variant pt-2 border-t border-outline-variant/30 mt-1.5">
                            {cleanReason(nextPair.node.reason) || '依据当前答题证据安排。'}
                            完成后将即时更新「{titleOf(nextPair.node.concept_id)}」的掌握证据。
                          </p>
                        </details>
                      </div>
                      <p className="font-body-md text-body-md text-on-surface-variant leading-relaxed">
                        {cleanReason(nextPair.node.reason) || '依据当前答题证据安排，先巩固最薄弱的环节。'}
                      </p>
                    </div>
                    <div className="flex items-center justify-end pt-space-2xs">
                      <button
                        className="px-space-lg py-space-xs rounded-lg bg-primary text-on-primary font-title-md text-title-md hover:bg-primary-container transition-all flex items-center gap-space-2xs active:scale-[0.99] shadow-sm"
                        onClick={() => navigate('/today')} type="button"
                      >
                        <span>开始作答</span>
                        <span className="material-symbols-outlined text-base">arrow_forward</span>
                      </button>
                    </div>
                  </article>
                )}

                {/* 知识点掌握与进展（stitch _2 紧凑行） */}
                <section className="bg-surface-container-lowest rounded-xl p-space-lg shadow-sm flex flex-col gap-space-md">
                  <div className="flex items-center justify-between">
                    <h2 className="font-headline-sm text-headline-sm text-on-surface">知识点掌握与进展</h2>
                    <span className="font-label-sm text-label-sm text-outline">未评估不计分 · 随作答动态更新</span>
                  </div>
                  <div className="flex flex-col gap-space-xs">
                    {mastery.map((m) => {
                      const pct = m.estimate === null ? null : Math.round(m.estimate * 100);
                      const unassessed = m.status === 'unassessed';
                      const weak = m.status === 'needs_support' || m.status === 'review_due';
                      const focus = workingNode?.concept_id === m.concept_id;
                      return (
                        <div
                          className={`p-space-sm rounded-lg flex flex-col gap-1 transition-colors ${
                            unassessed
                              ? 'bg-surface-container-lowest border border-outline-variant/30 hover:bg-surface-container-low opacity-70'
                              : weak
                                ? 'bg-secondary-fixed/20 border border-secondary-fixed-dim/40 hover:bg-secondary-fixed/30'
                                : focus
                                  ? 'bg-surface-container-low border border-primary-fixed-dim/50 hover:bg-surface-container'
                                  : 'bg-surface-container-lowest border border-outline-variant/40 hover:bg-surface-container-low'
                          }`}
                          key={m.concept_id}
                        >
                          <div className="flex flex-wrap items-center justify-between gap-space-xs">
                            <div className="flex items-center gap-space-xs">
                              {focus ? (
                                <span className="w-2 h-2 rounded-full bg-primary mr-1 animate-pulse" />
                              ) : (
                                <span
                                  className={`material-symbols-outlined text-base ${unassessed ? 'text-outline' : weak ? 'text-secondary' : 'text-primary'}`}
                                  style={unassessed ? undefined : { fontVariationSettings: "'FILL' 1" }}
                                >
                                  {unassessed
                                    ? 'radio_button_unchecked'
                                    : weak
                                      ? 'bookmark'
                                      : 'check_circle'}
                                </span>
                              )}
                              <span className={`font-title-md text-title-md ${unassessed ? 'text-outline font-medium' : 'text-on-surface font-semibold'}`}>
                                {m.title}
                              </span>
                              <span className={`px-space-xs py-0.5 rounded-full font-label-sm text-label-sm font-medium ${
                                unassessed
                                  ? 'bg-surface-container text-outline'
                                  : weak
                                    ? 'bg-secondary-fixed text-on-secondary-fixed'
                                    : focus
                                      ? 'bg-primary-fixed/60 text-primary'
                                      : 'bg-primary-fixed text-on-primary-fixed'
                              }`}>
                                {unassessed
                                  ? '尚未评估'
                                  : m.status === 'needs_support'
                                    ? '需要巩固'
                                    : m.status === 'review_due'
                                      ? '需要复习'
                                      : m.status === 'mastered'
                                        ? '已掌握'
                                        : focus ? '正在学习' : '学习中'}
                              </span>
                            </div>
                            <div className="flex items-center gap-space-sm">
                              {pct !== null && (
                                <span className={`font-label-sm text-label-sm font-medium ${weak ? 'text-secondary' : 'text-primary'}`}>
                                  估计掌握度 {pct}%
                                </span>
                              )}
                              {pct !== null && <span className="text-outline-variant">·</span>}
                              <span className="font-label-sm text-label-sm text-outline">{m.evidence_count} 条证据</span>
                            </div>
                          </div>
                          <details className={unassessed ? 'text-outline' : weak ? 'text-secondary' : 'text-outline'}>
                            <summary className="cursor-pointer hover:text-primary font-label-sm text-label-sm select-none list-none inline-flex items-center gap-0.5 pt-0.5">
                              <span>详细证据</span>
                              <span className="material-symbols-outlined text-xs">expand_more</span>
                            </summary>
                            <p className="font-body-sm text-body-sm text-on-surface-variant pt-1 border-t border-outline-variant/30 mt-1">
                              {unassessed
                                ? '尚未在作答中触发该部分的独立评估；未评估不计分。'
                                : `累计 ${m.evidence_count} 条独立作答证据${m.review_due_at ? `，推荐 ${shortDate(m.review_due_at)} 前安排复习复测` : ''}，支撑当前掌握状态。`}
                            </p>
                          </details>
                        </div>
                      );
                    })}
                  </div>
                </section>
              </div>

              {/* 右栏 */}
              <div className="lg:col-span-4 flex flex-col gap-space-lg min-w-0">
                <section className="bg-surface-container-lowest rounded-xl p-space-lg shadow-sm flex flex-col gap-space-md">
                  <div className="flex items-center justify-between">
                    <h3 className="font-headline-sm text-headline-sm text-on-surface">近期学习动态</h3>
                    <span className="font-label-sm text-label-sm text-outline">做题记录</span>
                  </div>
                  <div className="flex flex-col gap-space-sm">
                    {overview.recent_evidence.length === 0 && (
                      <div className="font-body-sm text-body-sm text-outline">暂无答题记录。</div>
                    )}
                    {overview.recent_evidence.map((e) => (
                      <div className="p-space-xs rounded-lg hover:bg-surface-container-low transition-colors flex items-center justify-between gap-space-xs" key={e.id}>
                        <div className="flex items-center gap-space-xs min-w-0">
                          <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${e.score === 1 ? 'bg-primary' : 'bg-secondary'}`} />
                          <span className="font-title-md text-title-md text-on-surface truncate">{titleOf(e.concept_id)}</span>
                        </div>
                        <div className="flex items-center gap-1.5 shrink-0 font-label-sm text-label-sm text-outline">
                          <span className="px-1 py-0.5 rounded bg-surface-container text-on-surface-variant text-[11px]">
                            {e.eligible ? '独立作答' : EXCLUSION_TEXT[e.exclusion_reason ?? ''] ?? '不计证据'}
                          </span>
                          <span>{relTime(e.created_at)}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                  <div className="mt-space-xs p-space-sm rounded-lg bg-surface-container flex items-center justify-between text-on-surface-variant font-label-sm text-label-sm">
                    <span>近 7 天作答</span>
                    <span className="font-semibold text-primary">
                      {overview.recent_evidence.filter((e) => Date.now() - new Date(e.created_at).getTime() < 7 * 24 * 3_600_000).length} 次
                    </span>
                  </div>
                </section>

                <aside className="bg-surface-container-lowest border border-outline-variant/40 rounded-xl p-space-md flex flex-col gap-space-xs shadow-sm">
                  <div className="flex items-center gap-space-2xs text-primary">
                    <span className="material-symbols-outlined text-base">info</span>
                    <span className="font-title-md text-title-md font-semibold">学情注记</span>
                  </div>
                  <p className="font-body-sm text-body-sm text-on-surface-variant leading-relaxed">
                    学情用于确定下一步动作，随练习即时更新，不设排名。
                  </p>
                </aside>
              </div>
            </div>

            {/* 页脚边缘注记（stitch _2 原版） */}
            <div className="flex items-center justify-between pt-space-md pb-space-lg text-outline">
              <span className="font-label-sm text-label-sm">
                学有所径 · 随练随测客观学情
              </span>
              <span className="font-label-sm text-label-sm">初中数学</span>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
