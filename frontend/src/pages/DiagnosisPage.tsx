/** 诊断模块（/profile/diagnosis）：作答（_2 卡）→ 结果（_3 原版结构），数据全部来自后端 */
import { useCallback, useEffect, useState } from 'react';

import { ApiError } from '../api/client';
import {
  completeAssessment, createGoal, getAssessment, getOverview,
  getPath, getSession, startDiagnosis, submitAttempt,
} from '../api/endpoints';
import type { PathData, PublicQuestion, SnapshotEntry } from '../api/types';
import { navigate } from '../lib/router';

type QuizItem = { exerciseId: string; exerciseVersion: number; question: PublicQuestion };

type Phase =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'question'; assessmentId: string; items: QuizItem[]; index: number; answeredBase: number; total: number }
  | { kind: 'result'; snapshot: SnapshotEntry[]; uncovered: string[]; planVersion: number; planOrder: string[]; reasons: Record<string, string> };

const DRAFT_KEY = 'xyj.diagnosis.drafts';

function loadDrafts(assessmentId: string): Record<string, string> {
  try {
    const all = JSON.parse(localStorage.getItem(DRAFT_KEY) ?? '{}') as Record<string, Record<string, string>>;
    return all[assessmentId] ?? {};
  } catch {
    return {};
  }
}

function persistDrafts(assessmentId: string, drafts: Record<string, string>): void {
  try {
    const all = JSON.parse(localStorage.getItem(DRAFT_KEY) ?? '{}') as Record<string, Record<string, string>>;
    all[assessmentId] = drafts;
    localStorage.setItem(DRAFT_KEY, JSON.stringify(all));
  } catch { /* 草稿仅用于刷新恢复，存储失败可忽略 */ }
}

function clearDrafts(assessmentId: string): void {
  try {
    const all = JSON.parse(localStorage.getItem(DRAFT_KEY) ?? '{}') as Record<string, Record<string, string>>;
    delete all[assessmentId];
    localStorage.setItem(DRAFT_KEY, JSON.stringify(all));
  } catch { /* 同上 */ }
}

const STATUS_TEXT: Record<string, string> = {
  mastered: '已掌握',
  developing: '初显掌握',
  needs_support: '建议起步巩固',
  unassessed: '尚未评估',
};

export function DiagnosisPage() {
  const [phase, setPhase] = useState<Phase>({ kind: 'loading' });
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const startWithRetry = useCallback(async (sessionId: string) => {
    const version = (await getSession(sessionId)).session.version;
    try {
      return await startDiagnosis(sessionId, version);
    } catch (e) {
      // 会话版本被并发更新（如双开标签页）→ 取最新版本重试一次（A09 自愈）
      if (e instanceof ApiError && e.code === 'version_conflict') {
        const fresh = (await getSession(sessionId)).session.version;
        return await startDiagnosis(sessionId, fresh);
      }
      throw e;
    }
  }, []);

  /** 顺着 after_exercise_id 链式取回本轮全部未作答题目（后端开局一次固定出题，提交即判分不可撤回） */
  const collectOpenQuestions = useCallback(async (
    assessmentId: string,
    first: { exercise: { id: string; version: number }; question: PublicQuestion },
  ): Promise<{ items: QuizItem[]; answeredCount: number }> => {
    const items: QuizItem[] = [
      { exerciseId: first.exercise.id, exerciseVersion: first.exercise.version, question: first.question },
    ];
    let afterId = first.exercise.id;
    let answeredCount = 0;
    for (;;) {
      const view = await getAssessment(assessmentId, afterId);
      if (items.length === 1) answeredCount = view.answered.length;
      if (!view.next) break;
      items.push({
        exerciseId: view.next.exercise.id,
        exerciseVersion: view.next.exercise.version,
        question: view.next.question,
      });
      afterId = view.next.exercise.id;
    }
    return { items, answeredCount };
  }, []);

  const boot = useCallback(async () => {
    try {
      const overview = await getOverview();
      const entry = overview.goals[0];
      let sessionId: string;
      if (!entry) {
        sessionId = (await createGoal('quadratic', [], 25)).session.id;
      } else {
        sessionId = (await getSession(entry.latest_session?.id ?? '')).session.id;
      }
      const detail = await getSession(sessionId);

      if (detail.resumable?.kind === 'diagnosis') {
        const assessmentId = detail.resumable.assessment.id;
        const view = await getAssessment(assessmentId);
        if (view.assessment.status === 'completed' || !view.next) {
          await finishToResult(assessmentId);
          return;
        }
        const { items, answeredCount } = await collectOpenQuestions(assessmentId, view.next);
        setDrafts(loadDrafts(assessmentId));
        setPhase({
          kind: 'question', assessmentId, items, index: 0,
          answeredBase: answeredCount, total: view.assessment.question_ids.length,
        });
        return;
      }

      const started = await startWithRetry(sessionId);
      if (!started.exercise || !started.question) {
        setPhase({ kind: 'error', message: '题库无可用新题族，已保留现有掌握估计。' });
        return;
      }
      const { items, answeredCount } = await collectOpenQuestions(
        started.assessment.id,
        { exercise: started.exercise, question: started.question },
      );
      setDrafts(loadDrafts(started.assessment.id));
      setPhase({
        kind: 'question', assessmentId: started.assessment.id, items, index: 0,
        answeredBase: answeredCount, total: started.assessment.question_ids.length,
      });
    } catch (e) {
      setPhase({ kind: 'error', message: e instanceof ApiError ? e.message : '加载诊断失败' });
    }
  }, [collectOpenQuestions, startWithRetry]);

  useEffect(() => { void boot(); }, [boot]);

  async function finishToResult(assessmentId: string) {
    const cur = await getAssessment(assessmentId);
    const done = await completeAssessment(assessmentId, cur.assessment.version);
    const reasons: Record<string, string> = {};
    const overview = await getOverview();
    if (overview.goals[0]) {
      const pathData: PathData = await getPath(overview.goals[0].goal.id);
      for (const n of pathData.nodes) reasons[n.concept_id] = n.reason;
    }
    setPhase({
      kind: 'result', snapshot: done.snapshot, uncovered: done.uncovered_concept_ids,
      planVersion: done.plan.version, planOrder: done.plan.ordered_concept_ids, reasons,
    });
  }

  function goTo(index: number) {
    setPhase((p) => (p.kind === 'question' ? { ...p, index } : p));
  }

  function goPrev() {
    if (phase.kind === 'question' && phase.index > 0) goTo(phase.index - 1);
  }

  function goNext() {
    if (phase.kind === 'question' && phase.index < phase.items.length - 1) goTo(phase.index + 1);
  }

  /** 草稿实时写入本地存储，刷新 / 中途退出后回到本页可恢复 */
  function updateDraft(value: string) {
    if (phase.kind !== 'question') return;
    const exerciseId = phase.items[phase.index].exerciseId;
    const next = { ...drafts, [exerciseId]: value };
    setDrafts(next);
    persistDrafts(phase.assessmentId, next);
  }

  /** 统一交卷：本地草稿逐题上报（已作答的以服务端为准，避免重复提交），随后完成诊断出结果 */
  async function submitAndFinish() {
    if (phase.kind !== 'question') return;
    setBusy(true); setError(null);
    try {
      const view = await getAssessment(phase.assessmentId);
      const doneIds = new Set(view.answered.map((a) => a.exercise_id));
      for (const item of phase.items) {
        if (doneIds.has(item.exerciseId)) continue;
        const value = (drafts[item.exerciseId] ?? '').trim();
        if (!value) continue; // 未作答即跳过：保留为未答
        await submitAttempt(item.exerciseId, value, item.exerciseVersion);
      }
      clearDrafts(phase.assessmentId);
      await finishToResult(phase.assessmentId);
    } catch (e) {
      setError(e instanceof ApiError ? `${e.code}: ${e.message}` : e instanceof Error ? e.message : '提交失败');
    } finally {
      setBusy(false);
    }
  }

  if (phase.kind === 'loading' || phase.kind === 'error') {
    return (
      <div className="pl-64">
        <main className="w-full pt-16 min-h-screen bg-surface">
          <div className="max-w-[720px] mx-auto px-gutter-desktop py-space-xl">
            {phase.kind === 'error' && (
              <>
                <div className="p-space-md rounded-xl bg-error-container text-on-error-container font-body-md mb-space-md">{phase.message}</div>
                <button className="px-space-lg py-space-sm rounded-lg bg-primary text-on-primary font-title-md text-title-md" onClick={() => navigate('/profile')}>返回学情总览</button>
              </>
            )}
            {phase.kind === 'loading' && <div className="pt-space-3xl text-center text-outline font-body-md">正在准备诊断…</div>}
          </div>
        </main>
      </div>
    );
  }

  // ---------- 结果页（_3 原版结构） ----------
  if (phase.kind === 'result') {
    const assessedList = phase.snapshot.filter((s) => s.status !== 'unassessed');
    const unassessedList = phase.snapshot.filter((s) => s.status === 'unassessed');
    const first = phase.planOrder.find((cid) => phase.snapshot.find((s) => s.concept_id === cid && s.status !== 'mastered'));
    const firstSnap = first ? phase.snapshot.find((s) => s.concept_id === first) : null;
    return (
      <div className="pl-64">
        <main className="w-full pt-16 min-h-screen bg-surface">
          <div className="w-full max-w-[1280px] mx-auto px-gutter-desktop pt-space-xl pb-space-3xl">
            <section className="flex flex-col gap-space-xl">
              <div className="flex flex-col md:flex-row md:items-end justify-between gap-space-md">
                <div>
                  <div className="flex items-center gap-space-xs mb-1.5">
                    <span className="px-space-xs py-0.5 rounded bg-surface-container text-primary font-label-sm text-label-sm font-medium">初三数学 · 二次函数</span>
                    <span className="font-label-sm text-label-sm text-outline">基于本轮诊断答题客观观察</span>
                  </div>
                  <h1 className="font-headline-lg text-headline-lg text-on-surface font-serif">这是目前了解到的学习情况</h1>
                  <p className="font-body-md text-body-md text-on-surface-variant mt-1">
                    诊断基于已作答题目的初步观察，未测部分在后续学习中逐步建立完整图谱，不设排名，不设能力天花板。
                  </p>
                </div>
                <div className="flex items-center gap-space-sm shrink-0">
                  <button className="px-space-md py-space-xs rounded-lg bg-surface-container-lowest text-on-surface font-title-md text-title-md border border-outline-variant hover:bg-surface-container transition-all flex items-center gap-1.5" onClick={() => navigate('/profile/conclusion')} type="button">
                    <span className="material-symbols-outlined text-[18px]">insights</span>AI 学情诊断报告
                  </button>
                  <button className="px-space-md py-space-xs rounded-lg bg-surface-container-lowest text-on-surface font-title-md text-title-md border border-outline-variant hover:bg-surface-container transition-all flex items-center gap-1.5" onClick={() => navigate('/profile/diagnosis')} type="button">
                    <span className="material-symbols-outlined text-[18px]">replay</span>继续补测
                  </button>
                  <button className="px-space-md py-space-xs rounded-lg bg-primary text-on-primary font-title-md text-title-md shadow-sm hover:bg-primary-container transition-all flex items-center gap-1.5" onClick={() => navigate('/today')} type="button">
                    <span className="material-symbols-outlined text-[18px]">bookmark_add</span>进入今日任务
                  </button>
                </div>
              </div>

              <div className="w-full bg-surface-container-lowest rounded-xl shadow-sm p-space-2xl border border-surface-variant relative overflow-hidden">
                <div className="absolute left-0 top-0 bottom-0 w-2.5 bg-secondary" />
                <div className="pl-space-sm">
                  <div className="flex flex-wrap items-center justify-between gap-space-md mb-space-sm">
                    <span className="px-space-sm py-1 rounded-full bg-secondary-fixed text-on-secondary-fixed-variant font-label-md text-label-md font-semibold flex items-center gap-1.5">
                      <span className="material-symbols-outlined text-[16px]">flag</span>智能自适应起点推荐
                    </span>
                    <span className="font-label-sm text-label-sm text-outline">结合本轮诊断与答题证据</span>
                  </div>
                  <h2 className="font-display-lg text-display-lg text-on-surface mb-space-md font-serif">
                    建议从【{first ? `${firstSnap?.concept_id ?? first} · ${firstSnap ? STATUS_TEXT[firstSnap.status] : ''}` : '巩固练习'}】开始
                  </h2>
                  <div className="p-space-lg rounded-xl bg-surface-container-low border border-outline-variant mb-space-xl">
                    <div className="flex items-start gap-space-sm">
                      <span className="material-symbols-outlined text-secondary text-[24px] shrink-0 mt-0.5">psychology</span>
                      <div className="w-full">
                        <div className="flex items-center gap-space-xs mb-1.5">
                          <span className="font-title-md text-title-md text-on-surface font-semibold">为什么这样安排？</span>
                          <span className="px-space-xs py-0.5 rounded bg-surface-container text-on-surface-variant font-label-sm text-label-sm">基于客观答题行为推导</span>
                        </div>
                        <p className="font-body-md text-body-md text-on-surface-variant leading-relaxed mb-space-sm">
                          {first ? phase.reasons[first] ?? '依据本轮作答证据，先巩固最薄弱、前置最成熟的知识点。' : '本轮各知识点均已达到当前阶段的观察目标，按计划继续推进。'}
                        </p>
                        <div className="flex flex-wrap items-center gap-space-md pt-space-xs border-t border-outline-variant text-label-sm text-on-surface-variant">
                          <span className="inline-flex items-center gap-1">
                            <span className="material-symbols-outlined text-[16px] text-primary">check_circle</span>
                            已评估 {assessedList.length} 个知识点
                          </span>
                          {unassessedList.length > 0 && (
                            <span className="inline-flex items-center gap-1">
                              <span className="material-symbols-outlined text-[16px] text-secondary">lightbulb</span>
                              未测 {unassessedList.length} 个：后续学习中继续了解
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-space-md">
                    <button className="px-space-xl py-space-sm rounded-lg bg-primary text-on-primary font-title-md text-title-md hover:bg-primary-container shadow-sm flex items-center gap-space-xs transition-all" onClick={() => navigate('/today')} type="button">
                      进入今日任务练习<span className="material-symbols-outlined text-[18px]">east</span>
                    </button>
                    <button className="px-space-lg py-space-sm rounded-lg bg-surface-container text-on-surface font-title-md text-title-md hover:bg-surface-container-high transition-colors flex items-center gap-space-xs" onClick={() => navigate('/path')} type="button">
                      <span className="material-symbols-outlined text-[18px]">playlist_add</span>查看推荐学习路径
                    </button>
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-space-lg">
                <div className="bg-surface-container-lowest rounded-xl shadow-sm p-space-xl border border-surface-variant">
                  <div className="flex items-center justify-between mb-space-md pb-space-xs border-b border-surface-variant">
                    <div className="flex items-center gap-space-xs">
                      <span className="w-3 h-3 rounded-full bg-primary" />
                      <h3 className="font-headline-sm text-headline-sm text-on-surface">已测内容观察</h3>
                    </div>
                    <span className="font-label-sm text-label-sm text-primary font-semibold px-space-xs py-0.5 rounded bg-primary-fixed/40">{assessedList.length} 项证据链</span>
                  </div>
                  <p className="font-body-sm text-body-sm text-outline mb-space-lg">
                    注：学习手册坚决拒绝仅凭一两道题判定“完全精通”，以下为客观答题行为初显与建议侧重：
                  </p>
                  <div className="flex flex-col gap-space-md">
                    {assessedList.map((s) => {
                      const pct = s.estimate === null ? 0 : Math.round(s.estimate * 100);
                      const weak = s.status === 'needs_support' || (s.estimate !== null && s.estimate < 0.5);
                      return (
                        <div className="p-space-md rounded-lg bg-surface-container-low border border-outline-variant" key={s.concept_id}>
                          <div className="flex flex-wrap items-center justify-between gap-1 mb-1.5">
                            <div className="flex items-center gap-space-xs">
                              <span className="font-title-md text-title-md text-on-surface font-semibold">{s.concept_id}</span>
                              <span className="px-space-xs py-0.5 rounded bg-surface-container text-outline font-label-sm text-label-sm">{s.evidence_count} 条客观证据</span>
                            </div>
                            <span className={`px-space-sm py-0.5 rounded-full font-label-sm text-label-sm font-medium ${weak ? 'bg-secondary-fixed text-on-secondary-fixed-variant' : 'bg-surface-container-highest text-on-surface'}`}>
                              {weak ? '建议起步巩固' : '初显掌握'}
                            </span>
                          </div>
                          <div className="flex items-center justify-between text-body-sm text-on-surface-variant mb-1">
                            <span>估计掌握度</span>
                            <span className={`font-semibold ${weak ? 'text-secondary' : 'text-primary'}`}>{pct}%</span>
                          </div>
                          <div className="w-full bg-surface-container-highest h-1.5 rounded-full overflow-hidden mb-space-xs">
                            <div className={`h-full rounded-full ${weak ? 'bg-secondary' : 'bg-primary'}`} style={{ width: `${pct}%` }} />
                          </div>
                          <p className="font-body-sm text-body-sm text-on-surface-variant">{STATUS_TEXT[s.status] ?? s.status}：{phase.reasons[s.concept_id] ?? '依据本轮作答证据生成。'}</p>
                        </div>
                      );
                    })}
                  </div>
                  <div className="mt-space-lg pt-space-sm flex items-center gap-space-xs text-outline font-label-sm text-label-sm border-t border-surface-variant">
                    <span className="material-symbols-outlined text-[16px]">info</span>
                    <span>依据标准：中考数学考纲 · 函数自适应推导规则集</span>
                  </div>
                </div>

                <div className="bg-surface-container-lowest rounded-xl shadow-sm p-space-xl flex flex-col justify-between border border-surface-variant">
                  <div>
                    <div className="flex items-center justify-between mb-space-md pb-space-xs border-b border-surface-variant">
                      <div className="flex items-center gap-space-xs">
                        <span className="w-3 h-3 rounded-full bg-outline-variant" />
                        <h3 className="font-headline-sm text-headline-sm text-on-surface">尚未评估模块</h3>
                      </div>
                      <span className="font-label-sm text-label-sm text-outline px-space-xs py-0.5 rounded bg-surface-container">后续逐步开放 · 不计入低分</span>
                    </div>
                    <p className="font-body-sm text-body-sm text-outline mb-space-lg">
                      未测内容不设默认“失分”或预设负向标签，只在未来日常主线练习中自然沉淀：
                    </p>
                    <div className="flex flex-col gap-space-md">
                      {unassessedList.length === 0 && (
                        <div className="p-space-md rounded-lg bg-surface-container text-outline font-body-sm">本轮诊断已覆盖全部目标知识点。</div>
                      )}
                      {unassessedList.map((s) => (
                        <div className="p-space-md rounded-lg bg-surface-container flex items-center justify-between border border-transparent hover:border-outline-variant transition-colors" key={s.concept_id}>
                          <div>
                            <span className="block font-title-md text-title-md text-on-surface font-medium">{s.concept_id}</span>
                            <span className="font-body-sm text-body-sm text-outline">本轮诊断未作答，后续学习中安排补测。</span>
                          </div>
                          <span className="px-space-sm py-1 rounded bg-surface-container-highest text-outline font-label-sm text-label-sm">
                            后续学习中继续了解
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                  <div className="mt-space-lg pt-space-sm flex items-center gap-space-xs text-outline font-label-sm text-label-sm border-t border-surface-variant">
                    <span className="material-symbols-outlined text-[16px]">explore</span>
                    <span>跟随每日主线任务自动激活下一单元评估</span>
                  </div>
                </div>
              </div>

              <footer className="p-space-lg rounded-xl bg-surface-container-low text-center border border-outline-variant">
                <p className="font-body-md text-body-md text-on-surface-variant font-medium">
                  “学情基于客观证据逐步沉淀，不设排名，不设能力天花板，专心走好每一步。”
                </p>
                <p className="font-label-sm text-label-sm text-outline mt-1">学有所径 · 自适应学习分析引擎提供支持</p>
              </footer>
            </section>
          </div>
        </main>
      </div>
    );
  }

  // ---------- 答题态（考试式导航：草稿本地暂存，交卷前可随意翻题修改） ----------
  const q: PublicQuestion = phase.items[phase.index].question;
  const currentDraft = drafts[phase.items[phase.index].exerciseId] ?? '';
  const isLast = phase.index >= phase.items.length - 1;
  const filledCount = phase.items.filter((item) => (drafts[item.exerciseId] ?? '').trim() !== '').length;
  return (
    <div className="pl-64">
      <main className="w-full pt-16 min-h-screen bg-surface">
        <div className="flex flex-col w-full">
          <div className="w-full max-w-[900px] mx-auto px-gutter-desktop py-space-lg flex flex-col gap-space-md">
            <div className="flex flex-wrap items-center justify-between gap-space-sm bg-surface-container-lowest px-space-md py-space-xs rounded-lg shadow-sm border border-outline-variant/40">
              <nav aria-label="Breadcrumb" className="flex items-center gap-2 font-label-md text-label-md text-outline">
                <span>自适应诊断</span>
                <span className="material-symbols-outlined text-[14px]">chevron_right</span>
                <span className="text-on-surface font-medium">{q.primary_concept_id} · 初筛</span>
              </nav>
              <div className="flex items-center gap-space-md">
                <div className="flex items-center gap-1 px-2.5 py-1 rounded-full bg-surface-container-high font-label-sm text-label-sm text-on-surface">
                  <span className="material-symbols-outlined text-[15px] text-primary">assignment</span>
                  <span>第 <strong>{phase.answeredBase + phase.index + 1}</strong> / {phase.total} 题</span>
                </div>
              </div>
            </div>

            <section className="bg-surface-container-lowest rounded-xl p-space-lg shadow-sm flex flex-col gap-space-lg relative overflow-hidden border border-outline-variant/40">
              <div className="flex items-center justify-between flex-wrap gap-2">
                <div className="flex items-center gap-2">
                  <span className="px-2.5 py-1 rounded-full bg-surface-container text-primary font-label-sm text-label-sm font-medium">题型 · {q.type === 'mcq' ? '选择题' : '数值输入'}</span>
                  <span className="px-2.5 py-1 rounded-full bg-surface-container-high text-on-surface-variant font-label-sm text-label-sm">难度：{'★'.repeat(q.difficulty)}{'☆'.repeat(3 - q.difficulty)}</span>
                </div>
                <span className="font-label-sm text-label-sm text-outline flex items-center gap-1">
                  <span className="material-symbols-outlined text-[16px]">touch_app</span> 可前后翻题、可暂停
                </span>
              </div>

              <div className="flex flex-col gap-space-sm pt-space-xs">
                <h1 className="font-headline-lg text-headline-lg text-on-surface font-semibold leading-relaxed">{q.prompt}</h1>
              </div>

              {q.type === 'mcq' ? (
                <div className="flex flex-col gap-2">
                  {q.public_options.map((opt) => (
                    <div
                      key={opt.key}
                      className={`flex items-center gap-3 p-3 rounded-lg cursor-pointer border transition-all ${currentDraft === opt.key ? 'bg-primary-light border-2 border-primary' : 'bg-surface-container-lowest border border-outline-variant/50 hover:border-primary hover:bg-surface-container-low'}`}
                      onClick={() => updateDraft(opt.key)}
                    >
                      <span className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold shrink-0 ${currentDraft === opt.key ? 'bg-primary text-on-primary' : 'bg-surface-container text-outline'}`}>{opt.key}</span>
                      <span className="font-body-lg text-body-lg text-on-surface">{opt.text}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <input
                  className="w-full px-4 py-3 bg-surface rounded-lg font-body-lg text-body-lg text-on-surface placeholder:text-outline-variant focus:bg-surface-container-lowest focus:outline-none focus:ring-2 focus:ring-primary/30 border border-outline-variant/50 shadow-xs"
                  placeholder="请输入你的答案（支持整数、小数或 p/q）"
                  value={currentDraft}
                  onChange={(e) => updateDraft(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter' && !busy) { if (isLast) void submitAndFinish(); else goNext(); } }}
                />
              )}

              {error && <div className="p-space-sm rounded-lg bg-error-container text-on-error-container font-body-md">{error}</div>}

              {phase.items.length > 1 && (
                <div className="flex flex-wrap items-center gap-1.5">
                  {phase.items.map((item, i) => {
                    const filled = (drafts[item.exerciseId] ?? '').trim() !== '';
                    const active = i === phase.index;
                    return (
                      <button
                        key={item.exerciseId}
                        onClick={() => goTo(i)}
                        disabled={busy}
                        type="button"
                        title={`第 ${phase.answeredBase + i + 1} 题${filled ? '（已填答案）' : ''}`}
                        className={`w-8 h-8 rounded-lg font-label-md text-label-md border transition-all ${active ? 'bg-primary text-on-primary border-primary shadow-sm' : filled ? 'bg-surface-container-high text-on-surface border-outline-variant/50 hover:border-primary' : 'bg-surface-container-lowest text-outline border-outline-variant/50 hover:border-primary'}`}
                      >
                        {phase.answeredBase + i + 1}
                      </button>
                    );
                  })}
                  <span className="font-label-sm text-label-sm text-outline ml-1">已填 {filledCount} 题，点编号可跳转</span>
                </div>
              )}

              <div className="flex flex-wrap items-center gap-space-sm">
                <button className="px-space-md py-2.5 rounded-lg bg-surface-container hover:bg-surface-container-high text-on-surface-variant font-title-md text-title-md transition-colors flex items-center gap-1 disabled:opacity-40 disabled:pointer-events-none" onClick={goPrev} disabled={busy || phase.index === 0} type="button">
                  <span className="material-symbols-outlined text-[18px]">arrow_back</span>上一题
                </button>
                <button className="px-space-md py-2.5 rounded-lg bg-surface-container hover:bg-surface-container-high text-on-surface-variant font-title-md text-title-md transition-colors flex items-center gap-1 disabled:opacity-40 disabled:pointer-events-none" onClick={goNext} disabled={busy || isLast} type="button">
                  下一题<span className="material-symbols-outlined text-[18px]">arrow_forward</span>
                </button>
                <button className="px-space-lg py-2.5 rounded-lg bg-primary text-on-primary font-title-md text-title-md font-medium hover:bg-primary-container active:scale-[0.98] transition-all flex items-center gap-2 shadow-sm disabled:opacity-50 ml-auto" onClick={submitAndFinish} disabled={busy} type="button">
                  <span className="material-symbols-outlined text-[18px]">task_alt</span>
                  <span>{busy ? '提交中…' : '提交并查看诊断结果'}</span>
                </button>
              </div>

              <div className="px-3 py-2 rounded-lg bg-surface-container/60 text-outline text-[12px] flex items-center gap-1.5">
                <span className="material-symbols-outlined text-sm text-outline">verified_user</span>
                <span>答案暂存本地，翻题修改不限次数；未作答的题直接翻过即可（不判错，对应知识点显示「尚未评估」）。</span>
              </div>
            </section>
          </div>
        </div>
      </main>
    </div>
  );
}
