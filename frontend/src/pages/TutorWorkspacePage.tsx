/** T12-D 启发辅导工作台：stitch stitch_ (18) 原版移植（全宽两栏：aside 260px + 主列）。
 *  真实数据：题目/练习 ← 会话可恢复练习；提示/解析/重做 ← T06 既有端点；
 *  思路分析与辅导轨迹 ← T12-B（thinking / tutoring-trace）。
 *  掌握度与证据规则如实展示：提示后订正不计入独立掌握证据。 */
import { useCallback, useEffect, useRef, useState } from 'react';

import { ApiError } from '../api/client';
import {
  getOverview, getSession, getTasks, getTutoringTrace, requestHint, requestSolution,
  submitAttempt, submitThinking,
} from '../api/endpoints';
import type { MasteryEntry, OverviewData, PublicQuestion, TasksData, ThinkingResult, TutoringTrace } from '../api/types';
import { navigate } from '../lib/router';

const SYMBOLS = ['x', 'y = ', '²', '/', '+', '-'];
const CN_LEVEL = ['一', '二', '三', '四'];

function hhmm(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

export function TutorWorkspacePage() {
  const [overview, setOverview] = useState<OverviewData | null>(null);
  const [tasks, setTasks] = useState<TasksData | null>(null);
  const [question, setQuestion] = useState<PublicQuestion | null>(null);
  const [trace, setTrace] = useState<TutoringTrace | null>(null);
  const [exerciseId, setExerciseId] = useState<string | null>(null);
  const [exerciseVersion, setExerciseVersion] = useState<number>(1);
  const [exerciseStatus, setExerciseStatus] = useState<string>('open');
  const [estimateMinutes] = useState<number>(5);
  const [thinking, setThinking] = useState<ThinkingResult | null>(null);
  const [thought, setThought] = useState('');
  const [answer, setAnswer] = useState('');
  const [hint, setHint] = useState<{ level: number; text: string } | null>(null);
  const [solution, setSolution] = useState<{ answer: string; solution: string; note: string } | null>(null);
  const [showSolution, setShowSolution] = useState(false);
  const [showWhy, setShowWhy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const goalEntry = overview?.goals[0] ?? null;
  const mastery: MasteryEntry[] = goalEntry?.mastery ?? [];

  const refreshTrace = useCallback(async (exId: string) => {
    const t = await getTutoringTrace(exId);
    setTrace(t);
    return t;
  }, []);

  const load = useCallback(async () => {
    const data = await getOverview();
    setOverview(data);
    const entry = data.goals[0];
    if (!entry || !entry.latest_session) return;
    try {
      setTasks(await getTasks(entry.goal.id));
    } catch { /* 任务缺失不阻塞 */ }
    const session = await getSession(entry.latest_session.id);
    const resumable = session.resumable;
    if (!resumable || resumable.kind !== 'learning') return;
    setExerciseId(resumable.exercise.id);
    setExerciseVersion(resumable.exercise.version);
    setExerciseStatus(resumable.exercise.status);
    setQuestion(resumable.question);
    const t = await getTutoringTrace(resumable.exercise.id);
    setTrace(t);
    if (t.hint_level > 0) {
      // 提示文本不回传历史，仅显示等级；重新请求会升级等级，故占位说明
      setHint({ level: t.hint_level, text: '（历史提示内容不重复展示，可点击「继续下一步提示」）' });
    }
  }, []);

  useEffect(() => {
    load().catch((e: ApiError) => setError(e.message));
  }, [load]);

  async function onSubmitThinking() {
    if (!exerciseId || !thought.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const { data: result } = await submitThinking(exerciseId, thought.trim());
      setThinking(result);
      await refreshTrace(exerciseId);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '提交思路失败');
    } finally {
      setBusy(false);
    }
  }

  async function onNextHint() {
    if (!exerciseId || busy) return;
    setBusy(true);
    setError(null);
    try {
      const h = await requestHint(exerciseId, exerciseVersion);
      setHint({ level: h.level, text: h.hint });
      setExerciseVersion(h.exercise_version);
      await refreshTrace(exerciseId);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '提示获取失败');
    } finally {
      setBusy(false);
    }
  }

  async function onSubmitAnswer() {
    if (!exerciseId || !answer.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const { data: result } = await submitAttempt(exerciseId, answer.trim(), exerciseVersion);
      setExerciseVersion(result.versions.exercise);
      setExerciseStatus(result.attempt.grade === 'correct' ? 'closed' : 'open');
      await refreshTrace(exerciseId);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '提交失败');
    } finally {
      setBusy(false);
    }
  }

  async function onShowSolution() {
    if (!exerciseId || solution) {
      setShowSolution((v) => !v);
      return;
    }
    setBusy(true);
    try {
      const s = await requestSolution(exerciseId, exerciseVersion);
      setSolution({ answer: s.answer, solution: s.solution, note: s.note });
      setExerciseVersion(s.exercise_version);
      setShowSolution(true);
      await refreshTrace(exerciseId);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '解析获取失败');
    } finally {
      setBusy(false);
    }
  }

  if (error && !overview) {
    return (
      <main className="min-h-screen bg-surface-bg pt-20 px-6">
        <div className="max-w-[900px] mx-auto p-space-md rounded-xl bg-error-container text-on-error-container font-body-md">{error}</div>
      </main>
    );
  }
  if (!overview) {
    return <main className="min-h-screen bg-surface-bg pt-20 px-6 text-center text-outline font-body-md">正在加载辅导工作台…</main>;
  }

  // ---------- 冷状态：无可辅导的练习 ----------
  if (!exerciseId || !question || !trace) {
    return (
      <main className="min-h-screen bg-surface-bg pt-20 px-6">
        <div className="max-w-[900px] mx-auto flex flex-col gap-space-md">
          <div className="flex items-center gap-3">
            <span className="px-2 py-0.5 rounded text-[11px] font-bold bg-primary-fixed text-on-primary-fixed-variant whitespace-nowrap">T12-D</span>
            <h1 className="text-[19px] font-bold text-slate-800 tracking-tight font-serif">一步一步解决，而不是直接告诉你答案</h1>
          </div>
          <div className="p-space-lg rounded-2xl bg-white border border-slate-200 shadow-xs text-center">
            <p className="text-sm text-slate-600">当前没有进行中的练习。先在今日任务清单开始一个任务，Tutor Agent 会在这里陪你逐步推导。</p>
            <button
              className="mt-space-md px-space-lg py-space-xs rounded-lg bg-primary-container text-white text-xs font-semibold shadow-sm hover:bg-primary-hover transition-colors"
              onClick={() => navigate('/today')}
              type="button"
            >
              去今日任务清单
            </button>
          </div>
        </div>
      </main>
    );
  }

  const conceptId = question.primary_concept_id;
  const masteryEntry = mastery.find((m) => m.concept_id === conceptId);
  const estimatePct = masteryEntry?.estimate != null ? Math.round(masteryEntry.estimate * 100) : null;
  const possibleProblem = thinking?.possible_problem ?? trace.latest_feedback?.possible_problem ?? null;
  const feedbackLine =
    thinking?.feedback ??
    trace.latest_feedback?.feedback ??
    (trace.timeline.some((t) => t.type === 'attempt' && t.grade === 'incorrect')
      ? '这次还没有答对，我们先一起检查你的思路。我不会直接公布答案，而是先给你一个适合当前阶段的提示。'
      : '先写下你的思路，再填写答案；遇到卡点就提交思路，我会给你适合当前阶段的提示。');
  const hintLevel = trace.hint_level;
  const remainingMinutes = tasks ? Math.max(tasks.budget_minutes - tasks.pending_minutes, 0) : studentRemaining(overview);

  // 今日研习清单（真实任务状态映射）
  const taskItems = (tasks?.tasks ?? []).map((t, i) => {
    const isCurrent = t.status === 'active';
    const state: 'done' | 'active' | 'todo' = t.status === 'completed' ? 'done' : isCurrent ? 'active' : 'todo';
    return { idx: i + 1, title: `第 ${i + 1} 题 · ${conceptTitle(mastery, t.concept_id)}`, state };
  });
  const doneCount = taskItems.filter((t) => t.state === 'done').length;

  return (
    <div className="min-h-screen bg-surface-bg">
      <main className="w-full px-6 pt-20 py-4 flex flex-col gap-3.5">
        {/* 工作台子标题 */}
        <div className="w-full flex flex-wrap items-center justify-between gap-3 pb-2.5 border-b border-slate-200">
          <div className="flex items-center gap-3">
            <span className="px-2 py-0.5 rounded text-[11px] font-bold bg-primary-fixed text-on-primary-fixed-variant whitespace-nowrap">T12-D</span>
            <h1 className="text-[19px] font-bold text-slate-800 tracking-tight font-serif flex items-center gap-2 whitespace-nowrap">
              一步一步解决，而不是直接告诉你答案
              <span className="inline-flex items-center gap-1 text-[11px] font-medium bg-primary-fixed/40 text-primary-container px-2 py-0.5 rounded-full border border-primary-fixed/80 whitespace-nowrap">
                <span className="material-symbols-outlined text-[13px]">smart_toy</span>
                Tutor Agent
              </span>
            </h1>
            <span className="hidden md:inline-block text-xs text-slate-500">| AI 会根据你的作答和思路，提供适合当前阶段的提示。</span>
          </div>
        </div>

        <div className="w-full flex flex-col lg:flex-row gap-5 items-start">
          {/* 左栏 */}
          <aside className="w-full lg:w-[260px] flex-shrink-0 flex flex-col gap-3.5">
            <div className="bg-white rounded-2xl p-4 border border-slate-200 shadow-xs">
              <div className="flex items-center justify-between mb-2.5">
                <div className="flex items-center gap-1.5 font-bold text-[14px] text-slate-800">
                  <span className="material-symbols-outlined text-primary-container text-[19px]">checklist_rtl</span>
                  <span>今日研习清单</span>
                </div>
                <span className="text-[11px] text-secondary font-medium bg-[#fff4ec] px-2 py-0.5 rounded-full whitespace-nowrap">
                  第 {Math.min(doneCount + 1, Math.max(taskItems.length, 1))} 题 / 共 {Math.max(taskItems.length, 1)} 题
                </span>
              </div>
              <div className="w-full bg-slate-100 h-1.5 rounded-full overflow-hidden mb-3">
                <div className="bg-primary-container h-full rounded-full transition-all duration-300" style={{ width: `${taskItems.length ? (doneCount / taskItems.length) * 100 : 0}%` }} />
              </div>
              <div className="flex flex-col gap-1.5">
                {taskItems.length === 0 && <div className="p-2 text-xs text-slate-400">今天还没有安排任务。</div>}
                {taskItems.map((item) => {
                  if (item.state === 'done') {
                    return (
                      <div className="flex items-center justify-between p-2 rounded-xl bg-slate-50 text-xs" key={item.idx}>
                        <div className="flex items-center gap-1.5 text-slate-500">
                          <span className="material-symbols-outlined text-primary-container text-[16px]">check_circle</span>
                          <span className="line-through text-slate-400">{item.title}</span>
                        </div>
                        <span className="text-[10px] text-primary-container font-medium bg-primary-fixed/30 px-1.5 py-0.5 rounded whitespace-nowrap">已掌握</span>
                      </div>
                    );
                  }
                  if (item.state === 'active') {
                    return (
                      <div className="flex items-center justify-between p-2 rounded-xl bg-primary-fixed/20 border border-primary-fixed text-xs font-semibold text-primary-container" key={item.idx}>
                        <div className="flex items-center gap-1.5">
                          <span className="w-2 h-2 rounded-full bg-primary-container animate-ping" />
                          <span>{item.title}</span>
                        </div>
                        <span className="text-[10px] text-white bg-primary-container px-1.5 py-0.5 rounded whitespace-nowrap">引导中</span>
                      </div>
                    );
                  }
                  return (
                    <div className="flex items-center justify-between p-2 rounded-xl bg-slate-50/70 text-xs text-slate-400" key={item.idx}>
                      <div className="flex items-center gap-1.5">
                        <span className="material-symbols-outlined text-[16px]">lock</span>
                        <span>{item.title}</span>
                      </div>
                      <span className="text-[10px] whitespace-nowrap">待开始</span>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="bg-white rounded-2xl p-3.5 border border-slate-200 shadow-xs flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="w-7 h-7 rounded-lg bg-slate-100 flex items-center justify-center text-primary-container">
                  <span className="material-symbols-outlined text-[17px]">timer</span>
                </div>
                <div className="flex flex-col">
                  <span className="text-xs font-semibold text-slate-800">今日研习时间</span>
                  <span className="text-[11px] text-slate-400">自适应平稳保护</span>
                </div>
              </div>
              <div className="flex flex-col items-end">
                <span className="text-xs font-bold text-primary-container">剩余 {remainingMinutes} 分钟</span>
                <span className="text-[10px] text-slate-400 flex items-center gap-0.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                  云端同步中
                </span>
              </div>
            </div>

            <div className="bg-white rounded-2xl p-4 border border-slate-200 shadow-xs">
              <div className="flex items-center justify-between mb-3 pb-2 border-b border-slate-100">
                <div className="flex items-center gap-1.5 font-bold text-[14px] text-slate-800">
                  <span className="material-symbols-outlined text-slate-500 text-[19px]">history_edu</span>
                  <span>作答与辅导轨迹</span>
                </div>
                <span className="text-[11px] text-slate-400 whitespace-nowrap">精炼时间线</span>
              </div>
              <div className="relative pl-3.5 space-y-2.5 text-xs before:content-[''] before:absolute before:left-1 before:top-2 before:bottom-2 before:w-0.5 before:bg-slate-200">
                {trace.timeline.map((item, i) => {
                  const dot =
                    item.type === 'attempt'
                      ? item.grade === 'correct' ? 'bg-primary-container' : 'bg-secondary'
                      : item.type === 'feedback' || item.type === 'thinking'
                        ? 'bg-primary-container'
                        : item.type === 'hint' || item.type === 'solution'
                          ? 'bg-primary-container'
                          : 'bg-slate-300';
                  return (
                    <div className="relative" key={i}>
                      <span className={`absolute -left-[14px] top-1 w-2 h-2 rounded-full ${dot} ring-2 ring-white`} />
                      <div className="flex flex-col gap-0.5">
                        <div className="flex items-center gap-2">
                          <span className="text-[11px] text-slate-400 font-mono">{hhmm(item.time)}</span>
                          <span className={`font-medium ${item.type === 'attempt' && item.grade === 'incorrect' ? 'text-slate-800 font-semibold' : 'text-slate-600'}`}>{item.label}</span>
                        </div>
                        {item.type === 'attempt' && item.grade === 'incorrect' && (
                          <span className="text-[10px] text-slate-500 font-mono pl-1.5 py-0.5 bg-slate-100 rounded inline-block w-fit">{item.answer}</span>
                        )}
                      </div>
                    </div>
                  );
                })}
                <div className="relative">
                  <span className="absolute -left-[14px] top-1 w-2 h-2 rounded-full bg-slate-400 ring-2 ring-white" />
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] text-slate-400 font-mono">当前</span>
                    <span className="text-slate-500">{trace.current.label}</span>
                  </div>
                </div>
              </div>
              <div className="mt-3.5 pt-2.5 border-t border-slate-100 flex items-start gap-1.5 text-[11px] text-slate-500 leading-tight">
                <span className="material-symbols-outlined text-[14px] text-primary-container shrink-0 mt-0.5">verified_user</span>
                <span>作答证据规则：提示后订正不计入独立掌握证据，订正后将安排同构迁移题。</span>
              </div>
            </div>
          </aside>

          {/* 主列 */}
          <div className="flex-1 w-full min-w-0 flex flex-col gap-3.5">
            {/* 题目卡 */}
            <div className="w-full bg-white rounded-2xl p-4 md:p-5 border border-slate-200 shadow-xs">
              <div className="flex items-center justify-between gap-2 pb-2.5 mb-2.5 border-b border-slate-100">
                <div className="flex items-center gap-2.5">
                  <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-primary-container text-white whitespace-nowrap">初三数学 · {conceptTitle(mastery, conceptId)}</span>
                  <span className="text-xs text-slate-500 font-medium whitespace-nowrap">预计用时 {estimateMinutes} 分钟</span>
                </div>
                <div className="flex items-center gap-1.5 text-xs text-secondary font-medium whitespace-nowrap">
                  <span className="w-1.5 h-1.5 rounded-full bg-secondary" />
                  <span>{masteryEntry?.status === 'mastered' ? '已掌握' : masteryEntry?.status === 'unassessed' ? '尚未评估' : '需要巩固'}</span>
                </div>
              </div>
              <div className="my-1">
                <h2 className="text-[17px] md:text-[18px] text-slate-800 font-serif font-bold leading-relaxed">{question.prompt}</h2>
              </div>
              <div className="mt-3 flex items-center justify-between text-xs text-slate-600 bg-slate-50 px-3.5 py-2 rounded-xl border border-slate-100">
                <div className="flex items-center gap-1.5">
                  <span className="material-symbols-outlined text-primary-container text-[17px]">lightbulb_circle</span>
                  <span className="font-medium">研习原则：请先写出你的思路，再填写答案。保留真实推导，系统不直接公开终值。</span>
                </div>
              </div>
            </div>

            {/* Tutor Agent 启发辅导 */}
            <div className="w-full bg-white rounded-2xl border-2 border-primary-container/40 shadow-sm p-4 md:p-5 relative overflow-hidden bg-gradient-to-b from-white via-white to-slate-50/50">
              <div className="flex items-center justify-between mb-3.5">
                <div className="flex items-center gap-2.5">
                  <div className="w-7 h-7 rounded-lg bg-primary-container text-white flex items-center justify-center shadow-xs">
                    <span className="material-symbols-outlined text-[18px]">forum</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <h3 className="font-bold text-[16px] text-slate-800 whitespace-nowrap">Tutor Agent 启发辅导</h3>
                    <span className="whitespace-nowrap px-2.5 py-0.5 text-xs rounded-full font-semibold bg-primary-fixed text-primary-container border border-primary-container/20">
                      {trace.timeline.some((t) => t.type === 'attempt' && t.grade === 'incorrect') ? '已识别困难' : '等待你的思路'}
                    </span>
                  </div>
                </div>
                <div className="whitespace-nowrap text-xs text-slate-400">引导式辅导</div>
              </div>

              {/* 错因与温和反馈 */}
              <div className="p-3.5 rounded-xl bg-[#fff4ec] border border-secondary-fixed text-secondary mb-3.5 flex items-start gap-2.5">
                <span className="material-symbols-outlined text-secondary text-[20px] shrink-0 mt-0.5">sentiment_neutral</span>
                <div className="flex flex-col gap-0.5">
                  <div className="text-[13px] font-bold text-on-secondary-container">{feedbackLine}</div>
                  {possibleProblem && (
                    <div className="text-[12px] text-on-secondary-container/90 mt-1">
                      <span className="font-semibold bg-secondary-fixed/60 px-1.5 py-0.5 rounded whitespace-nowrap">可能的问题：</span>
                      {possibleProblem}（这只是当前判断，后续练习后会继续确认）
                    </div>
                  )}
                </div>
              </div>

              {/* 苏格拉底式追问与思路 */}
              <div className="bg-slate-50 rounded-xl p-3.5 border border-slate-200 mb-3.5">
                <div className="flex items-start gap-2 mb-2.5">
                  <span className="material-symbols-outlined text-primary-container text-[19px] shrink-0 mt-0.5">psychology_alt</span>
                  <div className="text-[13px] text-slate-800">
                    <span className="font-bold text-primary-container">苏格拉底式追问：</span>
                    {thinking?.socratic_question ?? trace.latest_feedback?.socratic_question ?? '你在哪一步卡住了？把题目条件和你的式子逐条对应一下，告诉我第一处对不上的地方。'}
                  </div>
                </div>
                <div className="flex flex-col gap-1.5">
                  <div className="flex items-center justify-between text-xs text-slate-400">
                    <label className="font-medium text-slate-600 flex items-center gap-1" htmlFor="student-thought-box">
                      <span className="material-symbols-outlined text-[14px]">edit_note</span>
                      写下你的思考或困惑（系统会根据你的作答表现，逐步调整提示难度。）：
                    </label>
                    <span className="text-[11px] text-slate-400 whitespace-nowrap">支持自由草稿推导</span>
                  </div>
                  <textarea
                    className="w-full p-2.5 bg-white border border-slate-200 rounded-xl text-[13px] text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-primary-container focus:border-transparent transition-all resize-none h-18"
                    id="student-thought-box"
                    placeholder="例如：我不确定当顶点是 (2, -1) 时，括号内是减去 2 还是加上 2..."
                    value={thought}
                    onChange={(e) => setThought(e.target.value)}
                  />
                </div>
                <div className="mt-2.5 flex flex-wrap items-center justify-between gap-2 pt-1.5 border-t border-slate-200/70">
                  <div className="flex items-center gap-1.5 text-xs text-primary-container font-medium bg-primary-fixed/30 px-2.5 py-1 rounded-lg">
                    <span className="material-symbols-outlined text-[15px]">auto_awesome</span>
                    <span>
                      {thinking
                        ? `反馈：${thinking.feedback}`
                        : '反馈：提交思路后，我会给你适合当前阶段的判断（不会直接给答案）。'}
                    </span>
                  </div>
                  <button
                    className="px-3 py-1 bg-primary-container text-white rounded-lg text-xs font-semibold hover:bg-primary-hover transition-all shadow-xs flex items-center gap-1 whitespace-nowrap disabled:opacity-60"
                    disabled={busy || !thought.trim()}
                    onClick={onSubmitThinking}
                    type="button"
                  >
                    <span>{busy ? '分析中…' : '提交我的思路'}</span>
                    <span className="material-symbols-outlined text-[14px]">send</span>
                  </button>
                </div>
              </div>

              {/* 分级提示 */}
              {hintLevel > 0 && (
                <div className="rounded-xl border border-primary-fixed/80 bg-primary-fixed/15 p-3.5 mb-3.5 transition-all">
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-bold text-[13px] text-primary-container">① {CN_LEVEL[hintLevel - 1] ?? hintLevel}级提示：适合当前阶段的提示</span>
                    <span className="text-[11px] font-medium bg-white text-primary-container px-2 py-0.5 rounded border border-primary-fixed shadow-xs whitespace-nowrap">当前提示 {hintLevel} / 4</span>
                  </div>
                  <p className="text-[13px] text-slate-700 leading-relaxed pl-1">{hint?.text ?? '（历史提示内容不重复展示）'}</p>
                  <div className="mt-2.5 pl-1 flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-primary-fixed/40">
                    <div className="text-[11px] text-slate-500">说明：提示后原题重做不产生新的独立掌握证据。</div>
                    <div className="flex items-center gap-1.5">
                      <button
                        className="px-3 py-1 rounded-lg text-xs font-medium text-primary-container hover:bg-primary-fixed/40 bg-white border border-primary-fixed transition-colors flex items-center gap-1 shadow-xs whitespace-nowrap disabled:opacity-60"
                        disabled={busy || hintLevel >= 4 || exerciseStatus !== 'open'}
                        onClick={onNextHint}
                        type="button"
                      >
                        <span>继续下一步提示 →</span>
                      </button>
                      <span className="text-[11px] font-medium text-primary-container bg-white px-2 py-0.5 rounded border border-primary-fixed/80 whitespace-nowrap">提示 {hintLevel} / 4</span>
                    </div>
                  </div>
                </div>
              )}

              {/* 修改后重新作答 */}
              <div className="bg-slate-50 rounded-xl p-3.5 border border-slate-200">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[13px] font-bold text-slate-800 flex items-center gap-1.5">
                    <span className="material-symbols-outlined text-primary-container text-[18px]">draw</span>
                    修改后重新作答
                  </span>
                  <button className="text-[11px] text-slate-400 hover:text-error transition-colors flex items-center gap-0.5 whitespace-nowrap" onClick={() => setAnswer('')} type="button">
                    <span className="material-symbols-outlined text-[13px]">backspace</span>
                    清空输入
                  </button>
                </div>
                <div className="flex items-center gap-1.5 overflow-x-auto whitespace-nowrap pb-2">
                  <span className="text-[11px] text-slate-400 mr-1 shrink-0">快捷符号：</span>
                  {SYMBOLS.map((s) => (
                    <button
                      className="px-2.5 py-0.5 text-xs font-mono font-medium bg-white hover:bg-primary-fixed/30 border border-slate-200 rounded text-slate-700 transition-colors whitespace-nowrap shrink-0"
                      key={s}
                      onClick={() => {
                        setAnswer((v) => v + s);
                        inputRef.current?.focus();
                      }}
                      type="button"
                    >
                      {s.trim() === '' ? 'y =' : s}
                    </button>
                  ))}
                </div>
                <div className="relative mb-3">
                  <input
                    className="w-full px-3.5 py-2.5 bg-white border border-slate-200 rounded-xl text-[15px] font-mono font-medium text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-primary-container focus:border-transparent transition-all shadow-inner tracking-wide"
                    onChange={(e) => setAnswer(e.target.value)}
                    placeholder="输入你推导后的完整答案"
                    ref={inputRef}
                    type="text"
                    value={answer}
                  />
                </div>
                {exerciseStatus === 'open' ? (
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex flex-wrap items-center gap-2.5">
                      <button
                        className="px-5 py-2 rounded-xl text-[13px] font-bold bg-primary-container text-white hover:bg-primary-hover active:scale-[0.98] transition-all shadow-sm flex items-center gap-1.5 whitespace-nowrap disabled:opacity-60"
                        disabled={busy || !answer.trim()}
                        onClick={onSubmitAnswer}
                        type="button"
                      >
                        <span>{busy ? '核验中…' : '提交答案 →'}</span>
                      </button>
                      <span className="text-[11px] text-slate-500">修改后可以重新提交，系统会保留本次作答记录，修改后订正不计入独立掌握证据。</span>
                    </div>
                    <button className="text-xs text-slate-500 hover:text-slate-800 transition-colors flex items-center gap-0.5 underline underline-offset-2 whitespace-nowrap" onClick={onShowSolution} type="button">
                      <span>还是不清楚？{showSolution ? '收起完整解析 ▴' : '查看完整解析 ▾'}</span>
                    </button>
                  </div>
                ) : (
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex items-center gap-2 text-[13px] font-semibold text-primary-container">
                      <span className="material-symbols-outlined text-[18px]">check_circle</span>
                      本题已完成（提示后订正不计入独立掌握证据）。
                    </div>
                    <button
                      className="px-4 py-1.5 rounded-lg bg-primary-container text-white text-xs font-semibold hover:bg-primary-hover transition-colors flex items-center gap-1"
                      onClick={() => navigate('/today')}
                      type="button"
                    >
                      <span>去完成同构迁移练习 →</span>
                    </button>
                  </div>
                )}
                {showSolution && solution && (
                  <div className="mt-3 p-3.5 bg-white rounded-xl border border-slate-200 text-xs transition-all shadow-xs">
                    <div className="p-2 bg-error-container/40 text-error rounded-lg mb-2 font-medium flex items-center gap-1.5">
                      <span className="material-symbols-outlined text-[16px]">warning</span>
                      <span>明确规则提示：查看完整解析后，本题不产生独立掌握证据。完成查看后请直接进行变式迁移练习。</span>
                    </div>
                    <div className="space-y-1.5 text-slate-700 leading-relaxed pl-1 whitespace-pre-wrap">{solution.solution}</div>
                    <div className="mt-3 pt-2 border-t border-slate-100 flex justify-end">
                      <button
                        className="px-3 py-1 rounded-lg bg-primary-container text-white text-xs font-semibold hover:bg-primary-hover transition-colors flex items-center gap-1"
                        onClick={() => navigate('/today')}
                        type="button"
                      >
                        <span>开始迁移练习 →</span>
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* 学情通栏 */}
            <div className="w-full bg-white rounded-2xl border border-slate-200 shadow-xs overflow-hidden">
              <div className="px-4 py-2.5 flex flex-wrap items-center justify-between gap-3 bg-slate-50/70 select-none">
                <div className="flex items-center gap-2 text-xs">
                  <span className="material-symbols-outlined text-primary-container text-[18px]">insights</span>
                  <span className="font-semibold text-slate-800">当前学情：</span>
                  <span className="font-bold text-primary-container bg-primary-fixed/40 px-2 py-0.5 rounded-full whitespace-nowrap">
                    {estimatePct === null ? '尚未评估' : `掌握度 ${estimatePct}%`}
                  </span>
                  <span className="text-slate-300">·</span>
                  {possibleProblem && <span className="text-secondary font-medium bg-[#fff4ec] px-2 py-0.5 rounded text-[11px] whitespace-nowrap">{possibleProblem}</span>}
                  <span className="text-slate-400 text-[11px] whitespace-nowrap">(已使用 {hintLevel} / 4 级提示)</span>
                </div>
                <button
                  className="text-xs font-semibold text-slate-700 hover:text-primary-container transition-colors flex items-center gap-1 px-2.5 py-1 rounded-lg hover:bg-white border border-transparent hover:border-slate-200 whitespace-nowrap"
                  onClick={() => setShowWhy((v) => !v)}
                  type="button"
                >
                  <span>为什么给我这个提示？ {showWhy ? '▴' : '▾'}</span>
                </button>
              </div>
              {showWhy && (
                <div className="p-4 border-t border-slate-200/80 bg-white grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
                  <div className="p-3 rounded-xl bg-slate-50 border border-slate-100 flex flex-col gap-2">
                    <div className="font-bold text-slate-800 flex items-center gap-1.5">
                      <span className="material-symbols-outlined text-primary-container text-[16px]">school</span>
                      <span>当前学情详情</span>
                    </div>
                    <div className="text-slate-600 leading-relaxed space-y-1">
                      <div><strong className="text-slate-700">当前知识点：</strong>{conceptTitle(mastery, conceptId)}</div>
                      <div>
                        <strong className="text-slate-700">掌握度：</strong>
                        {estimatePct === null
                          ? <span className="text-slate-500">尚未评估</span>
                          : <span className="text-primary-container font-bold font-mono">{estimatePct}%</span>}
                      </div>
                      <div><strong className="text-slate-700">当前判断：</strong>{possibleProblem ?? '暂无（提交思路后生成）'}</div>
                      <div><strong className="text-slate-700">提示使用状态：</strong>已使用 {hintLevel} / 4 级提示</div>
                    </div>
                  </div>
                  <div className="p-3 rounded-xl bg-slate-50 border border-slate-100 flex flex-col gap-2">
                    <div className="font-bold text-slate-800 flex items-center gap-1.5">
                      <span className="material-symbols-outlined text-primary-container text-[16px]">psychology</span>
                      <span>Agent 决策依据透明度</span>
                    </div>
                    <div className="text-slate-600 leading-relaxed space-y-1">
                      <div><strong className="text-slate-700">反馈来源：</strong>{thinking?.planner_source === 'llm' ? `在线模型 ${thinking.model_id ?? ''}` : '规则回退（模型不可用时保证不阻塞）'}</div>
                      <div><strong className="text-slate-700">提示规则：</strong>首答错误只给反馈与追问；连续请求按 1→4 级逐层提示。</div>
                      <div><strong className="text-slate-700">证据规则：</strong>首答、无提示、未看解析才计入独立掌握证据。</div>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {error && <div className="p-2.5 rounded-xl bg-error-container text-on-error-container text-xs">{error}</div>}
          </div>
        </div>
      </main>
    </div>
  );
}

function conceptTitle(mastery: MasteryEntry[], conceptId: string): string {
  return mastery.find((m) => m.concept_id === conceptId)?.title ?? conceptId;
}

function studentRemaining(overview: OverviewData): number {
  return overview.student.daily_minutes;
}
