/** 学习工作台：stitch _2（独立练习）+ _1（答错辅导）同页双态原版移植，数据全部来自后端 */
import { useCallback, useEffect, useState } from 'react';

import { ApiError } from '../api/client';
import {
  acknowledgeTask, getExerciseAttempts, getOverview, getPath, getSession, getTasks,
  pauseSession, requestHint, requestSolution, resumeSession, sendMessage, startNextTask, submitAttempt,
} from '../api/endpoints';
import type { MasteryEntry, PublicQuestion, TaskDto } from '../api/types';
import { navigate } from '../lib/router';

interface ActiveLesson {
  kind: 'lesson';
  taskId: string; taskVersion: number; conceptId: string;
  title: string; excerpt: string;
}
interface ActiveExercise {
  kind: 'practice' | 'review';
  taskId: string; conceptId: string;
  exerciseId: string; exerciseVersion: number;
  question: PublicQuestion;
  hintLevel: number;
}
type Active = ActiveLesson | ActiveExercise;

interface ChatTurn { from: 'me' | 'ai'; text: string; source?: string }

interface SubmittedAttempt {
  answer: string;
  grade: string;
  hint_level: number;
  created_at: string;
}

export function WorkbenchPage() {
  const [bootError, setBootError] = useState<string | null>(null);
  const [goalId, setGoalId] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionStatus, setSessionStatus] = useState<string | null>(null);
  const [tasks, setTasks] = useState<TaskDto[]>([]);
  const [budget, setBudget] = useState<{ pending: number; total: number; within: boolean } | null>(null);
  const [active, setActive] = useState<Active | null>(null);
  // 当前练习的历史提交（只读展示）；草稿与历史分离，绝不回填覆盖
  const [attempts, setAttempts] = useState<SubmittedAttempt[]>([]);
  const [prevRecord, setPrevRecord] = useState<SubmittedAttempt[] | null>(null); // 原题（迁移前）作答记录
  const [taskDone, setTaskDone] = useState<TaskDto | null>(null);
  const [correctNote, setCorrectNote] = useState<string | null>(null);
  const [hint, setHint] = useState<{ level: number; text: string } | null>(null);
  const [hintOpen, setHintOpen] = useState(false);
  const [solution, setSolution] = useState<{ answer: string; text: string } | null>(null);
  const [thinkOpen, setThinkOpen] = useState(false);
  const [solutionModal, setSolutionModal] = useState(false);
  const [mastery, setMastery] = useState<MasteryEntry[]>([]);
  const [nodeReasons, setNodeReasons] = useState<Record<string, string>>({});
  const [chat, setChat] = useState<ChatTurn[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [answer, setAnswer] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const [pageError, setPageError] = useState<string | null>(null);
  const [thinkingSince, setThinkingSince] = useState<number | null>(null);

  useEffect(() => {
    if (thinkingSince === null) return;
    const t = setInterval(() => setThinkingSince((s) => (s === null ? s : s + 1)), 1000);
    return () => clearInterval(t);
  }, [thinkingSince]);

  const fmtTimer = (s: number) => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;

  const freshVersion = useCallback(async (): Promise<number> => {
    if (!sessionId) throw new ApiError('no_session', '会话缺失', 500);
    const detail = await getSession(sessionId);
    setSessionStatus(detail.session.status);
    return detail.session.version;
  }, [sessionId]);

  // 历史提交记录（只读），供作答记录展示；草稿不从这里取
  const syncAttempts = useCallback(async (exerciseId: string) => {
    try {
      const data = await getExerciseAttempts(exerciseId);
      setAttempts(data.attempts.map((a) => ({
        answer: a.answer, grade: a.grade, hint_level: a.hint_level_at_submission, created_at: a.created_at,
      })));
    } catch {
      setAttempts([]);
    }
  }, []);

  const refreshSurroundings = useCallback(async (_sid: string, gid: string) => {
    const [overview, tasksData] = await Promise.all([getOverview(), getTasks(gid)]);
    setTasks(tasksData.tasks);
    setBudget({ pending: tasksData.pending_minutes, total: tasksData.budget_minutes, within: tasksData.within_budget });
    if (overview.goals[0]) setMastery(overview.goals[0].mastery);
  }, []);

  const loadPathReasons = useCallback(async (gid: string) => {
    const pathData = await getPath(gid);
    const map: Record<string, string> = {};
    for (const n of pathData.nodes) map[n.concept_id] = n.reason;
    setNodeReasons(map);
  }, []);

  const boot = useCallback(async () => {
    try {
      const overview = await getOverview();
      const entry = overview.goals[0];
      if (!entry || !entry.latest_session) { navigate('/'); return; }
      const gid = entry.goal.id;
      const sid = entry.latest_session.id;
      setGoalId(gid); setSessionId(sid);
      await refreshSurroundings(sid, gid);
      await loadPathReasons(gid);
      const detail = await getSession(sid);
      setSessionStatus(detail.session.status);
      if (detail.resumable?.kind === 'learning') {
        const res = detail.resumable;
        setActive({
          kind: 'practice', taskId: '', conceptId: res.question.primary_concept_id,
          exerciseId: res.exercise.id, exerciseVersion: res.exercise.version,
          question: res.question, hintLevel: res.exercise.hint_level,
        });
        setThinkingSince(0);
        await syncAttempts(res.exercise.id);
      }
    } catch (e) {
      setBootError(e instanceof ApiError ? e.message : '加载工作台失败');
    }
  }, [refreshSurroundings, loadPathReasons, syncAttempts]);

  useEffect(() => { void boot(); }, [boot]);

  async function startTask() {
    if (!sessionId) return;
    setBusy(true); setPageError(null);
    setFeedbackReset();
    try {
      const result = await startNextTask(sessionId, await freshVersion());
      if ('content' in result) {
        setActive({ kind: 'lesson', taskId: result.task.id, taskVersion: result.task.version, conceptId: result.task.concept_id, title: result.content.title, excerpt: result.content.excerpt });
      } else {
        setActive({
          kind: result.task.type === 'review' ? 'review' : 'practice',
          taskId: result.task.id, conceptId: result.question.primary_concept_id,
          exerciseId: result.exercise.id, exerciseVersion: result.exercise.version,
          question: result.question, hintLevel: result.exercise.hint_level ?? 0,
        });
        setThinkingSince(0);
      }
      await refreshSurroundings(sessionId, goalId ?? '');
    } catch (e) {
      setPageError(e instanceof ApiError ? e.message : '启动任务失败');
    } finally {
      setBusy(false);
    }
  }

  function setFeedbackReset() {
    setAttempts([]); setPrevRecord(null); setHint(null); setHintOpen(false); setSolution(null);
    setAnswer(''); setSelected(null); setThinkOpen(false); setTaskDone(null); setCorrectNote(null);
  }

  async function acknowledge() {
    if (!active || active.kind !== 'lesson') return;
    setBusy(true); setPageError(null);
    try {
      await acknowledgeTask(active.taskId, active.taskVersion);
      setActive(null);
      await refreshSurroundings(sessionId ?? '', goalId ?? '');
    } catch (e) {
      setPageError(e instanceof ApiError ? e.message : '确认失败');
    } finally {
      setBusy(false);
    }
  }

  async function submitAnswer() {
    if (!active || active.kind === 'lesson') return;
    const value = active.question.type === 'mcq' ? selected : answer.trim();
    if (!value) { setPageError('请先作答'); return; }
    setBusy(true); setPageError(null);
    try {
      // 只发送当前草稿 draftAnswer，绝不拼接历史提交
      const res = await submitAttempt(active.exerciseId, value, active.exerciseVersion);
      const result = res.data;
      setAttempts((prev) => [...prev, {
        answer: value, grade: result.attempt.grade,
        hint_level: result.attempt.hint_level_at_submission,
        created_at: new Date().toISOString(),
      }]);
      // 提交后清空草稿，允许完整删除/重新输入
      setAnswer(''); setSelected(null);
      if (result.attempt.grade === 'correct') {
        setHint(null); setHintOpen(false); setSolution(null);
        setCorrectNote(
          result.evidence.eligible
            ? '独立完成，本次作答已计入掌握证据。'
            : result.evidence.exclusion_reason === 'not_first_attempt'
              ? '原题重做完成，不计新增独立掌握证据；继续完成下方同类新题验证。'
              : `辅助完成（${result.evidence.exclusion_reason ?? ''}），不计入独立掌握证据。`,
        );
        if (res.next_action?.type === 'next_question') {
          const view = await getSession(sessionId ?? '');
          if (view.resumable?.kind === 'learning') {
            const nextId = view.resumable.exercise.id;
            setPrevRecord([...attempts, {
              answer: value, grade: result.attempt.grade,
              hint_level: result.attempt.hint_level_at_submission,
              created_at: new Date().toISOString(),
            }]);
            setActive({
              ...active, kind: 'practice', conceptId: view.resumable.question.primary_concept_id,
              exerciseId: nextId, exerciseVersion: view.resumable.exercise.version,
              question: view.resumable.question, hintLevel: view.resumable.exercise.hint_level,
            });
            setAttempts([]);
            await syncAttempts(nextId);
            setThinkingSince(0);
          } else {
            setPrevRecord([...attempts, {
              answer: value, grade: result.attempt.grade,
              hint_level: result.attempt.hint_level_at_submission,
              created_at: new Date().toISOString(),
            }]);
            setActive(null);
          }
        } else {
          setPrevRecord([...attempts, {
            answer: value, grade: result.attempt.grade,
            hint_level: result.attempt.hint_level_at_submission,
            created_at: new Date().toISOString(),
          }]);
          setTaskDone({
            id: active.taskId, concept_id: active.conceptId, type: active.kind,
            status: 'completed', estimated_minutes: 5, version: 0,
          });
          setActive(null);
        }
      } else {
        // 答错辅导态：练习保持 open，草稿已清空，可直接重新输入完整答案
        setCorrectNote(null);
        setHint(null); setHintOpen(false); setSolution(null);
      }
      if (sessionId) await refreshSurroundings(sessionId, goalId ?? '');
    } catch (e) {
      setPageError(e instanceof ApiError ? e.message : '提交失败');
    } finally {
      setBusy(false);
    }
  }

  async function askHint() {
    if (!active || active.kind === 'lesson') return;
    setBusy(true); setPageError(null);
    try {
      const result = await requestHint(active.exerciseId, active.exerciseVersion);
      setHint({ level: result.level, text: result.hint });
      setHintOpen(true);
      setActive({ ...active, exerciseVersion: result.exercise_version, hintLevel: result.level });
    } catch (e) {
      setPageError(e instanceof ApiError ? e.message : '提示请求失败');
    } finally {
      setBusy(false);
    }
  }

  async function showSolution() {
    if (!active || active.kind === 'lesson') return;
    setBusy(true); setPageError(null);
    try {
      const result = await requestSolution(active.exerciseId, active.exerciseVersion);
      setSolution({ answer: result.answer, text: result.solution });
      setHint(null); setHintOpen(false); setSolutionModal(false);
      setActive({ ...active, exerciseVersion: result.exercise_version });
    } catch (e) {
      setPageError(e instanceof ApiError ? e.message : '解析请求失败');
    } finally {
      setBusy(false);
    }
  }

  async function sendChat() {
    if (!sessionId || !chatInput.trim()) return;
    const text = chatInput.trim();
    setChatInput('');
    setChat((c) => [...c, { from: 'me', text }]);
    setBusy(true);
    try {
      const result = await sendMessage(sessionId, text, await freshVersion());
      setChat((c) => [...c, { from: 'ai', text: result.reply, source: `决策：${result.decision.action} · ${result.decision.planner_source}${result.decision.model_id ? ` · ${result.decision.model_id}` : ''}` }]);
    } catch (e) {
      setChat((c) => [...c, { from: 'ai', text: e instanceof ApiError ? e.message : '暂时无法回复' }]);
    } finally {
      setBusy(false);
    }
  }

  async function pause() {
    if (!sessionId) return;
    setBusy(true);
    try {
      await pauseSession(sessionId, await freshVersion());
      setSessionStatus('paused');
      navigate('/profile');
    } catch (e) {
      setPageError(e instanceof ApiError ? e.message : '暂停失败');
      setBusy(false);
    }
  }

  async function resume() {
    if (!sessionId) return;
    setBusy(true); setPageError(null);
    try {
      const r = await resumeSession(sessionId, await freshVersion());
      setSessionStatus(r.session.status);
      const detail = await getSession(sessionId);
      if (detail.resumable?.kind === 'learning') {
        const res = detail.resumable;
        setActive({
          kind: 'practice', taskId: '', conceptId: res.question.primary_concept_id,
          exerciseId: res.exercise.id, exerciseVersion: res.exercise.version,
          question: res.question, hintLevel: res.exercise.hint_level,
        });
        setThinkingSince(0);
        await syncAttempts(res.exercise.id);
      } else {
        setActive(null);
        setAttempts([]);
      }
    } catch (e) {
      setPageError(e instanceof ApiError ? e.message : '恢复失败');
    } finally {
      setBusy(false);
    }
  }

  if (bootError) {
    return (
      <div className="pl-64">
        <main className="w-full pt-16 min-h-screen bg-surface">
          <div className="px-gutter-desktop py-space-lg">
            <div className="p-space-md rounded-xl bg-error-container text-on-error-container font-body-md">{bootError}</div>
          </div>
        </main>
      </div>
    );
  }

  const currentMastery = active ? mastery.find((m) => m.concept_id === active.conceptId) : undefined;
  const currentReason = active ? nodeReasons[active.conceptId] : undefined;
  const completedCount = tasks.filter((t) => t.status === 'completed').length;
  const progressPct = tasks.length > 0 ? Math.round((completedCount / tasks.length) * 100) : 0;
  const question = active && active.kind !== 'lesson' ? active.question : null;
  // 草稿是唯一可编辑来源；历史提交仅用于展示（attempts）
  const lastAttempt = attempts.length > 0 ? attempts[attempts.length - 1] : null;
  const wrongState = question !== null && lastAttempt !== null && lastAttempt.grade === 'incorrect';

  const recordPanel = attempts.length > 0 && (
    <div className="p-space-md rounded-xl bg-surface-container-lowest border border-outline-variant/50 flex flex-col gap-2">
      <div className="flex items-center justify-between pb-1 border-b border-surface-container">
        <div className="flex items-center gap-2">
          <span className="material-symbols-outlined text-primary text-[18px]">history</span>
          <span className="font-title-md text-title-md text-on-surface font-semibold">作答记录</span>
          <span className="px-2 py-0.5 rounded-full bg-surface-container text-outline font-label-sm text-label-sm">只读</span>
        </div>
      </div>
      {attempts.map((a, i) => (
        <div className="flex items-center justify-between gap-3 p-2 rounded-lg bg-surface-container/60" key={i}>
          <div className="flex items-center gap-2 min-w-0">
            <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${a.grade === 'correct' ? 'bg-status-mastered' : 'bg-secondary'}`} />
            <span className="font-mono text-sm text-on-surface truncate">{a.answer}</span>
            {a.hint_level > 0 && (
              <span className="px-1.5 py-0.5 rounded bg-secondary-fixed/50 text-secondary text-[11px] font-medium shrink-0">提示 {a.hint_level}/4 后</span>
            )}
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-full ${a.grade === 'correct' ? 'bg-status-mastered-bg text-status-mastered' : 'bg-secondary-light text-secondary-dark border border-secondary-border'}`}>
              {a.grade === 'correct' ? '答对' : '未通过'}
            </span>
            <span className="font-label-sm text-label-sm text-outline">
              {i === 0 && a.hint_level === 0 ? '已计证据' : '不计独立证据'}
            </span>
          </div>
        </div>
      ))}
      <div className="font-label-sm text-label-sm text-outline">
        提示后/原题重做/查看解析后的再次提交均会保留在此，但不产生新的独立掌握证据。
      </div>
    </div>
  );

  return (
    <div className="pl-64">
            <main className="w-full pt-16 min-h-screen bg-surface">
        <div className="flex flex-col w-full">
          <div className="w-full px-gutter-desktop py-space-md">
            <div className="max-w-[1400px] mx-auto flex flex-col gap-space-lg">

              {pageError && (
                <div className="p-space-sm rounded-lg bg-error-container text-on-error-container font-body-md">{pageError}</div>
              )}

              {/* 今日任务摘要：从侧栏移入工作区顶部，保留进度信息但不占用主练习栏。 */}
              <section className="bg-surface-container-lowest rounded-xl p-space-md shadow-sm border border-outline-variant/40 flex flex-wrap items-center gap-space-md">
                <div className="flex items-center gap-space-xs"><span className="material-symbols-outlined text-primary text-[20px]">fact_check</span><span className="font-title-md text-title-md text-on-surface font-semibold">今日任务</span></div>
                <span className="px-2 py-0.5 rounded-full bg-surface-container-high text-on-surface-variant font-label-sm text-label-sm">预计 {budget ? budget.pending : '—'} 分钟</span>
                <div className="flex items-center gap-space-sm min-w-[220px] flex-1"><span className="font-label-sm text-label-sm text-on-surface-variant whitespace-nowrap">已完成 {completedCount} / 共 {tasks.length} 步</span><div className="flex-1 h-1.5 bg-surface-container-high rounded-full overflow-hidden"><div className="h-full bg-primary rounded-full transition-all duration-500" style={{ width: `${progressPct}%` }} /></div><span className="font-label-sm text-label-sm font-semibold text-primary">{progressPct}%</span></div>
              </section>

              <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_300px] gap-space-lg items-start">

                {/* ============ 左栏：今日任务（_2 原版） ============ */}
                <aside className="hidden" aria-hidden="true">
                  <div className="bg-surface-container-lowest rounded-xl p-space-md shadow-sm flex flex-col gap-space-md border border-outline-variant/40">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-space-xs">
                        <span className="material-symbols-outlined text-primary text-[20px]">fact_check</span>
                        <span className="font-title-md text-title-md text-on-surface font-semibold">今日任务</span>
                      </div>
                      <span className="px-2 py-0.5 rounded-full bg-surface-container-high text-on-surface-variant font-label-sm text-label-sm">
                        预计 {budget ? budget.pending : '—'} 分钟
                      </span>
                    </div>

                    <div className="flex flex-col gap-1.5 pt-1">
                      <div className="flex items-center justify-between font-label-sm text-label-sm">
                        <span className="text-on-surface-variant">已完成 {completedCount} / 共 {tasks.length} 步</span>
                        <span className="font-semibold text-primary">{progressPct}%</span>
                      </div>
                      <div className="w-full h-1.5 bg-surface-container-high rounded-full overflow-hidden">
                        <div className="h-full bg-primary rounded-full transition-all duration-500" style={{ width: `${progressPct}%` }} />
                      </div>
                    </div>

                    <div className="flex flex-col gap-space-xs pt-space-xs relative">
                      {tasks.length > 0 && (
                        <div className="absolute left-[13px] top-4 bottom-4 w-0.5 bg-surface-container-high -z-0" />
                      )}
                      {tasks.map((t, i) => {
                        const done = t.status === 'completed';
                        const current = t.status === 'active';
                        const locked = t.status === 'cancelled';
                        return (
                          <div
                            key={t.id}
                            className={`relative z-10 flex items-start gap-space-sm p-2 rounded-lg ${current ? 'bg-surface-container-low border border-primary/20 transition-all' : 'hover:bg-surface-container-low transition-colors'} ${locked ? 'opacity-60' : ''}`}
                          >
                            <div className={`w-6 h-6 rounded-full flex items-center justify-center shrink-0 mt-0.5 shadow-sm ${done ? 'bg-primary text-on-primary' : current ? 'bg-surface-container-lowest text-primary border border-outline-variant/40' : 'bg-surface-container-lowest text-outline-variant border border-outline-variant/40'}`}>
                              {done ? (
                                <span className="material-symbols-outlined text-[16px]">check</span>
                              ) : current ? (
                                <div className="w-2.5 h-2.5 rounded-full bg-primary animate-pulse" />
                              ) : (
                                <span className="material-symbols-outlined text-[16px]">lock</span>
                              )}
                            </div>
                            <div className="flex flex-col min-w-0">
                              <div className="flex items-center gap-1.5">
                                <span className={`font-title-md text-title-md ${done ? 'text-on-surface font-medium line-through decoration-outline-variant' : current ? 'text-primary font-semibold' : 'text-on-surface-variant font-medium'}`}>
                                  {t.concept_id} · {t.type === 'lesson' ? '讲解' : t.type === 'practice' ? '独立练习' : '复习验证'}
                                </span>
                                <span className={`px-1.5 py-0.2 rounded font-label-sm text-[11px] ${done ? 'bg-surface-container text-outline' : current ? 'bg-primary text-on-primary' : 'bg-surface-container text-outline'}`}>
                                  {done ? '已完成' : current ? '当前' : locked ? '已调整' : '待开始'}
                                </span>
                              </div>
                              <span className="font-label-sm text-label-sm text-outline mt-0.5 truncate">{t.estimated_minutes} 分钟</span>
                            </div>
                            <span className="hidden">{i}</span>
                          </div>
                        );
                      })}
                      {tasks.length === 0 && (
                        <div className="font-label-sm text-label-sm text-outline">完成诊断后，规划器会在此生成今日任务。</div>
                      )}
                    </div>

                    <div className="p-space-sm rounded-lg bg-secondary-fixed/30 border border-secondary-container/20 flex items-start gap-space-xs mt-space-2xs">
                      <span className="material-symbols-outlined text-secondary text-[18px] shrink-0 mt-0.5">lightbulb</span>
                      <p className="font-label-sm text-label-sm text-on-surface-variant leading-relaxed">
                        <strong className="font-medium text-on-surface">阶段提示：</strong>完成独立练习后，将自适应匹配 1 道拓展变式。
                      </p>
                    </div>
                  </div>

                  <div className="bg-surface-container-lowest rounded-xl p-space-md shadow-sm flex flex-col gap-2 border border-outline-variant/40">
                    <span className="font-label-sm text-label-sm text-outline uppercase tracking-wider">今日预算</span>
                    <div className="flex items-baseline gap-2">
                      <span className="font-display-lg text-display-lg text-on-surface font-semibold">{budget ? budget.total - budget.pending : '—'}</span>
                      <span className="font-label-md text-label-md text-on-surface-variant">/ {budget ? budget.total : '—'} 分钟</span>
                    </div>
                    <div className="flex items-center gap-1.5 text-primary font-label-sm text-label-sm">
                      <span className="material-symbols-outlined text-[16px]">speed</span>
                      <span>按自身节奏推进，不设倒计时</span>
                    </div>
                  </div>
                </aside>

                {/* ============ 中栏：作答与辅导（_2 + _1 双态） ============ */}
                <main className="flex flex-col gap-space-md w-full min-w-0">
                  {!active && sessionStatus === 'diagnosing' && (
                    <div className="bg-surface-container-lowest rounded-xl p-space-lg shadow-sm border border-outline-variant/40 text-center py-space-3xl">
                      <div className="w-12 h-12 mx-auto rounded-full bg-surface-container flex items-center justify-center text-primary mb-space-sm">
                        <span className="material-symbols-outlined text-2xl">quiz</span>
                      </div>
                      <h2 className="font-headline-sm text-headline-sm text-on-surface font-semibold mb-1">有一轮诊断进行到一半</h2>
                      <p className="font-body-sm text-body-sm text-outline mb-space-md">先完成剩余的诊断题，完成后规划器会安排今日任务。</p>
                      <button className="px-space-lg py-2.5 rounded-lg bg-primary text-on-primary font-title-md text-title-md hover:bg-primary-container active:scale-[0.98] transition-all shadow-sm inline-flex items-center gap-2" onClick={() => navigate('/profile/diagnosis')}>
                        <span>继续诊断</span>
                        <span className="material-symbols-outlined text-[18px]">arrow_forward</span>
                      </button>
                    </div>
                  )}
                  {!active && sessionStatus === 'paused' && (
                    <div className="bg-surface-container-lowest rounded-xl p-space-lg shadow-sm border border-outline-variant/40 text-center py-space-3xl">
                      <div className="w-12 h-12 mx-auto rounded-full bg-surface-container flex items-center justify-center text-primary mb-space-sm">
                        <span className="material-symbols-outlined text-2xl">pause_circle</span>
                      </div>
                      <h2 className="font-headline-sm text-headline-sm text-on-surface font-semibold mb-1">学习已暂停</h2>
                      <p className="font-body-sm text-body-sm text-outline mb-space-md">题目、提示等级与作答记录都已保存，恢复后回到原处。</p>
                      <button className="px-space-lg py-2.5 rounded-lg bg-primary text-on-primary font-title-md text-title-md hover:bg-primary-container active:scale-[0.98] transition-all shadow-sm inline-flex items-center gap-2" onClick={resume} disabled={busy}>
                        <span>{busy ? '恢复中…' : '恢复学习'}</span>
                        <span className="material-symbols-outlined text-[18px]">play_arrow</span>
                      </button>
                    </div>
                  )}
                  {!active && sessionStatus !== 'paused' && budget !== null && budget.pending === 0 && (
                    <div className="bg-surface-container-lowest rounded-xl p-space-lg shadow-sm border border-outline-variant/40 text-center py-space-3xl">
                      <div className="w-12 h-12 mx-auto rounded-full bg-surface-container flex items-center justify-center text-primary mb-space-sm">
                        <span className="material-symbols-outlined text-2xl">psychology_alt</span>
                      </div>
                      <h2 className="font-headline-sm text-headline-sm text-on-surface font-semibold mb-1">今日没有待办任务</h2>
                      <p className="font-body-sm text-body-sm text-outline mb-space-md">再做一轮诊断补测更多知识点，或等计划器生成新的复习安排。</p>
                      <button className="px-space-lg py-2.5 rounded-lg bg-primary text-on-primary font-title-md text-title-md hover:bg-primary-container active:scale-[0.98] transition-all shadow-sm inline-flex items-center gap-2" onClick={() => navigate('/profile/diagnosis')}>
                        <span>去诊断</span>
                        <span className="material-symbols-outlined text-[18px]">arrow_forward</span>
                      </button>
                    </div>
                  )}
                  {!active && sessionStatus !== 'paused' && budget !== null && budget.pending > 0 && (
                    <div className="bg-surface-container-lowest rounded-xl p-space-lg shadow-sm border border-outline-variant/40 text-center py-space-3xl">
                      <div className="w-12 h-12 mx-auto rounded-full bg-surface-container flex items-center justify-center text-primary mb-space-sm">
                        <span className="material-symbols-outlined text-2xl">play_circle</span>
                      </div>
                      <h2 className="font-headline-sm text-headline-sm text-on-surface font-semibold mb-1">准备开始下一个任务</h2>
                      <p className="font-body-sm text-body-sm text-outline mb-space-md">规划器已按「复习到期 → 补测 → 薄弱优先」排好顺序。</p>
                      <button className="px-space-lg py-2.5 rounded-lg bg-primary text-on-primary font-title-md text-title-md hover:bg-primary-container active:scale-[0.98] transition-all shadow-sm inline-flex items-center gap-2" onClick={startTask} disabled={busy}>
                        <span>{busy ? '启动中…' : '开始下一个任务'}</span>
                        <span className="material-symbols-outlined text-[18px]">arrow_forward</span>
                      </button>
                    </div>
                  )}

                  {active?.kind === 'lesson' && (
                    <div className="bg-surface-container-lowest rounded-xl p-space-lg shadow-sm flex flex-col gap-space-md border border-outline-variant/40">
                      <div className="flex items-center justify-between flex-wrap gap-2">
                        <div className="flex items-center gap-2">
                          <span className="px-2.5 py-1 rounded-full bg-surface-container text-primary font-label-sm text-label-sm font-medium">讲解 · {active.conceptId}</span>
                          <span className="px-2.5 py-1 rounded-full bg-surface-container-high text-on-surface-variant font-label-sm text-label-sm">阅读后确认</span>
                        </div>
                      </div>
                      <h1 className="font-headline-lg text-headline-lg text-on-surface font-semibold">{active.title}</h1>
                      <div className="p-space-md rounded-lg bg-surface-container-low font-body-lg text-body-lg text-on-surface leading-relaxed whitespace-pre-wrap">{active.excerpt}</div>
                      <div className="p-space-sm rounded-lg bg-surface-container/60 text-outline text-[12px] flex items-center gap-1.5">
                        <span className="material-symbols-outlined text-sm text-outline">verified_user</span>
                        <span>讲解本身不产生掌握证据；确认后进入练习，独立答对才计入。</span>
                      </div>
                      <button className="px-space-lg py-2.5 rounded-lg bg-primary text-on-primary font-title-md text-title-md hover:bg-primary-container active:scale-[0.98] transition-all shadow-sm flex items-center justify-center gap-2" onClick={acknowledge} disabled={busy}>
                        <span className="material-symbols-outlined text-[18px]">check</span>
                        <span>我已理解，完成讲解任务</span>
                      </button>
                    </div>
                  )}

                  {(active?.kind === 'practice' || active?.kind === 'review') && question && (
                    <>
                      <div className="flex flex-wrap items-center justify-between gap-space-sm bg-surface-container-lowest px-space-md py-space-xs rounded-lg shadow-sm border border-outline-variant/40">
                        <nav aria-label="Breadcrumb" className="flex items-center gap-2 font-label-md text-label-md text-outline">
                          <span>二次函数</span>
                          <span className="material-symbols-outlined text-[14px]">chevron_right</span>
                          <span>{active.conceptId}</span>
                          <span className="material-symbols-outlined text-[14px]">chevron_right</span>
                          <span className="text-on-surface font-medium">{active.kind === 'review' ? '复习验证' : '独立练习'}</span>
                        </nav>
                        <div className="flex items-center gap-space-md">
                          <div className="flex items-center gap-1 px-2.5 py-1 rounded-full bg-surface-container-high font-label-sm text-label-sm text-on-surface">
                            <span className="material-symbols-outlined text-[15px] text-primary">assignment</span>
                            <span>{active.kind === 'review' ? '复习' : '练习'} · {question.family_id}</span>
                          </div>
                          {thinkingSince !== null && !wrongState && (
                            <div className="flex items-center gap-1 px-2.5 py-1 rounded-full bg-secondary-fixed/40 font-label-sm text-label-sm text-on-secondary-fixed">
                              <span className="material-symbols-outlined text-[15px] text-secondary">schedule</span>
                              <span>已思考 {fmtTimer(thinkingSince)}</span>
                            </div>
                          )}
                          <button className="font-label-sm text-label-sm text-outline hover:text-on-surface flex items-center gap-1 transition-colors" onClick={pause} disabled={busy} type="button">
                            <span className="material-symbols-outlined text-[16px]">pause_circle</span>
                            <span>暂停并保存</span>
                          </button>
                        </div>
                      </div>

                      <section className="bg-surface-container-lowest rounded-xl p-space-lg shadow-sm flex flex-col gap-space-lg relative overflow-hidden border border-outline-variant/40">
                        <div className="flex items-center justify-between flex-wrap gap-2">
                          <div className="flex items-center gap-2">
                            <span className="px-2.5 py-1 rounded-full bg-surface-container text-primary font-label-sm text-label-sm font-medium">
                              题型 · {question.type === 'mcq' ? '选择题' : '数值输入'}
                            </span>
                            <span className="px-2.5 py-1 rounded-full bg-surface-container-high text-on-surface-variant font-label-sm text-label-sm">
                              难度：{'★'.repeat(question.difficulty)}{'☆'.repeat(3 - question.difficulty)}
                            </span>
                          </div>
                          <span className="font-label-sm text-label-sm text-outline flex items-center gap-1">
                            <span className="material-symbols-outlined text-[16px]">touch_app</span> 单题自测
                          </span>
                        </div>

                        <div className="flex flex-col gap-space-sm pt-space-xs">
                          <h1 className="font-headline-lg text-headline-lg text-on-surface font-semibold leading-relaxed tracking-normal">{question.prompt}</h1>
                        </div>

                        {question.type === 'mcq' ? (
                          <div className="flex flex-col gap-2">
                            {question.public_options.map((opt) => (
                              <div
                                key={opt.key}
                                className={`flex items-center gap-3 p-3 rounded-lg cursor-pointer border transition-all ${selected === opt.key ? 'bg-primary-light border-2 border-primary' : 'bg-surface-container-lowest border border-outline-variant/50 hover:border-primary hover:bg-surface-container-low'}`}
                                onClick={() => setSelected(opt.key)}
                              >
                                <span className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold shrink-0 ${selected === opt.key ? 'bg-primary text-on-primary' : 'bg-surface-container text-outline'}`}>{opt.key}</span>
                                <span className="font-body-lg text-body-lg text-on-surface">{opt.text}</span>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <div className="flex flex-col gap-space-sm pt-space-xs">
                            <label className="font-label-md text-label-md text-on-surface font-medium flex items-center justify-between">
                              <span>你的作答：</span>
                              {wrongState && (
                                <span className="text-secondary font-normal font-label-sm flex items-center gap-1">
                                  <span className="material-symbols-outlined text-sm">edit_note</span>
                                  <span>可直接删除重输，提交内容 = 当前输入框内容</span>
                                </span>
                              )}
                            </label>
                            <div className="relative flex items-center">
                              <input
                                className={`w-full px-4 py-3 rounded-lg font-body-lg text-body-lg text-on-surface placeholder:text-outline-variant focus:outline-none focus:ring-2 focus:ring-primary/30 border shadow-xs transition-all ${wrongState ? 'bg-surface-container-low ring-2 ring-secondary-container/70 border-secondary-container/70' : 'bg-surface border border-outline-variant/50'}`}
                                placeholder="请输入你的答案（支持整数、小数或 p/q）"
                                value={answer}
                                onChange={(e) => setAnswer(e.target.value)}
                                onKeyDown={(e) => { if (e.key === 'Enter' && !busy) void submitAnswer(); }}
                              />
                            </div>
                          </div>
                        )}

                        {wrongState && (
                          <div className="p-space-md rounded-xl bg-secondary-fixed/35 border border-secondary-container/40 flex flex-col gap-space-sm shadow-xs">
                            <div className="flex items-center gap-2 text-secondary font-title-md text-title-md font-semibold">
                              <span className="material-symbols-outlined text-xl text-secondary">lightbulb</span>
                              <span>还差一点，我们先说说思路</span>
                            </div>
                            <p className="font-body-md text-body-md text-on-surface leading-relaxed">
                              这次作答未通过判定。这道题会保持打开，你可以修改后重新提交，或先要一条提示。
                            </p>
                            <div className="flex flex-wrap items-center gap-space-sm pt-1">
                              <button className="px-space-md py-2 rounded-lg bg-surface-container-lowest hover:bg-surface-container border border-outline-variant/60 text-on-surface font-label-md text-label-md shadow-xs flex items-center gap-1.5 transition-colors" onClick={() => setThinkOpen(true)} type="button">
                                <span className="material-symbols-outlined text-base text-secondary">mic</span>
                                <span>说说思路</span>
                              </button>
                              <button className="px-space-md py-2 rounded-lg bg-secondary text-on-secondary hover:bg-secondary/90 font-label-md text-label-md shadow-xs flex items-center gap-1.5 transition-colors" onClick={askHint} disabled={busy} type="button">
                                <span className="material-symbols-outlined text-base">tips_and_updates</span>
                                <span>{hint ? `给我一点提示（提示 ${hint.level} / 4）` : '给我一点提示'}</span>
                              </button>
                            </div>
                          </div>
                        )}

                        {hint && hintOpen && (
                          <div className="p-space-md rounded-xl bg-surface-container-lowest border border-outline-variant/60 flex flex-col gap-space-sm transition-all">
                            <div className="flex items-center justify-between pb-1 border-b border-surface-container">
                              <div className="flex items-center gap-2">
                                <span className="px-2 py-0.5 rounded-full bg-secondary text-on-secondary font-label-sm text-label-sm font-semibold">提示 {hint.level} / 4</span>
                                <span className="font-title-md text-title-md text-on-surface font-semibold">启发引导</span>
                              </div>
                              <span className="font-label-sm text-label-sm text-outline">后置提示已锁定</span>
                            </div>
                            <p className="font-body-md text-body-md text-on-surface leading-relaxed">{hint.text}</p>
                            <div className="flex items-center gap-space-sm pt-1">
                              <button className="px-space-md py-1.5 rounded-lg bg-primary text-on-primary font-title-md text-title-md shadow-xs transition-colors" onClick={askHint} disabled={busy || hint.level >= 4} type="button">
                                {hint.level >= 4 ? '已是最后一级提示' : '继续要下一级提示'}
                              </button>
                            </div>
                          </div>
                        )}

                        {correctNote && (
                          <div className="p-space-md rounded-xl bg-secondary-fixed/35 border border-secondary-container/40 flex flex-col gap-space-sm shadow-xs">
                            <div className="flex items-center gap-2 text-secondary font-title-md text-title-md font-semibold">
                              <span className="material-symbols-outlined text-xl text-secondary">check_circle</span>
                              <span>作答结果</span>
                            </div>
                            <p className="font-body-md text-body-md text-on-surface leading-relaxed">{correctNote}</p>
                          </div>
                        )}

                        {prevRecord && (
                          <div className="p-space-md rounded-xl bg-surface-container-low border border-outline-variant/50 flex flex-col gap-2">
                            <div className="flex items-center gap-2">
                              <span className="material-symbols-outlined text-outline text-[18px]">history</span>
                              <span className="font-title-md text-title-md text-on-surface font-semibold">原题作答记录</span>
                              <span className="px-2 py-0.5 rounded-full bg-surface-container text-outline font-label-sm text-label-sm">不计新增独立证据</span>
                            </div>
                            {prevRecord.map((a, i) => (
                              <div className="flex items-center justify-between gap-3 p-2 rounded-lg bg-surface-container-lowest" key={i}>
                                <div className="flex items-center gap-2 min-w-0">
                                  <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${a.grade === 'correct' ? 'bg-status-mastered' : 'bg-secondary'}`} />
                                  <span className="font-mono text-sm text-on-surface truncate">{a.answer}</span>
                                </div>
                                <span className={`text-[11px] font-semibold ${a.grade === 'correct' ? 'text-status-mastered' : 'text-secondary-dark'}`}>
                                  {a.grade === 'correct' ? '答对' : '未通过'}
                                </span>
                              </div>
                            ))}
                          </div>
                        )}

                        {recordPanel}

                        {pageError && (
                          <div className="p-space-sm rounded-lg bg-error-container text-on-error-container font-body-md">{pageError}</div>
                        )}

                        <div className="flex flex-wrap items-center gap-space-sm pt-space-xs">
                          <button className="flex-1 min-w-[200px] py-space-sm px-space-md rounded-lg bg-primary text-on-primary hover:bg-primary-container font-title-md text-title-md transition-all shadow-sm flex items-center justify-center gap-1.5" onClick={submitAnswer} disabled={busy} type="button">
                            <span className="material-symbols-outlined text-base">check</span>
                            <span>{wrongState ? '修改后重新提交' : '提交答案'}</span>
                            <span className="material-symbols-outlined text-[18px]">arrow_forward</span>
                          </button>
                          {!wrongState && (
                            <button className="py-space-sm px-space-md rounded-lg bg-secondary-fixed/50 hover:bg-secondary-fixed text-on-secondary-fixed font-title-md text-title-md font-medium transition-all flex items-center gap-1.5 border border-secondary-container/30" onClick={askHint} disabled={busy} type="button">
                              <span className="material-symbols-outlined text-[18px] text-secondary">lightbulb</span>
                              <span>给我一点提示</span>
                            </button>
                          )}
                          {wrongState && (
                            <button className="py-space-sm px-space-md rounded-lg bg-surface-container hover:bg-surface-container-high text-on-surface-variant font-title-md text-title-md transition-colors" onClick={() => setHintOpen(!hintOpen)} disabled={!hint} type="button">
                              {hintOpen ? '收起提示' : '展开提示'}
                            </button>
                          )}
                        </div>

                        <div className="pt-space-sm border-t border-surface-container flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 text-body-sm">
                          <div className="flex items-center gap-1.5 text-on-surface-variant">
                            <span className="material-symbols-outlined text-sm text-primary">psychology</span>
                            <span className="font-label-sm text-label-sm">自主思考订正，有助于长效理解与技能内化</span>
                          </div>
                          {!solution && (
                            <button className="font-label-sm text-label-sm text-outline hover:text-secondary hover:underline transition-colors flex items-center gap-0.5" onClick={() => setSolutionModal(true)} type="button">
                              <span className="material-symbols-outlined text-sm">visibility</span>
                              <span>还是理不清？查看完整解析</span>
                            </button>
                          )}
                        </div>

                        <div className="px-3 py-2 rounded-lg bg-surface-container/60 text-outline text-[12px] flex items-center gap-1.5">
                          <span className="material-symbols-outlined text-sm text-outline">verified_user</span>
                          <span>注：查看完整解析后，系统将为你推送一道同类变式题，用于确认独立掌握。</span>
                        </div>

                        {solution && (
                          <div className="p-space-md rounded-xl bg-secondary-fixed/35 border border-secondary-container/40 flex flex-col gap-space-sm">
                            <div className="flex items-center gap-2 text-secondary font-title-md text-title-md font-semibold">
                              <span className="material-symbols-outlined text-xl">verified_user</span>
                              <span>完整解析</span>
                            </div>
                            <p className="font-body-md text-body-md text-on-surface leading-relaxed">答案：{solution.answer}</p>
                            <p className="font-body-md text-body-md text-on-surface leading-relaxed">{solution.text}</p>
                            <p className="font-label-sm text-label-sm text-outline">本题已标记为「查看解析」，不再产生独立掌握证据；接下来请完成同类新题验证。</p>
                          </div>
                        )}
                      </section>

                      {taskDone && !active && (
                        <div className="bg-surface-container-lowest rounded-xl p-space-lg shadow-sm border border-outline-variant/40 flex flex-col gap-space-md">
                          <div className="flex items-center gap-2 text-primary font-title-md text-title-md font-semibold">
                            <span className="material-symbols-outlined text-xl">task_alt</span>
                            <span>任务已完成 · {taskDone.concept_id} {taskDone.type === 'lesson' ? '讲解' : taskDone.type === 'practice' ? '独立练习' : '复习验证'}</span>
                          </div>
                          {recordPanel}
                          <div className="flex flex-wrap items-center gap-space-sm">
                            <button className="px-space-lg py-2.5 rounded-lg bg-primary text-on-primary font-title-md text-title-md hover:bg-primary-container active:scale-[0.98] transition-all shadow-sm flex items-center gap-2" onClick={startTask} disabled={busy} type="button">
                              <span>开始下一个任务</span>
                              <span className="material-symbols-outlined text-[18px]">arrow_forward</span>
                            </button>
                            <button className="px-space-md py-2.5 rounded-lg bg-surface-container hover:bg-surface-container-high text-on-surface-variant font-title-md text-title-md transition-colors" onClick={() => navigate('/records/mastery')} type="button">
                              查看掌握度变化
                            </button>
                          </div>
                        </div>
                      )}

                      <details className="group rounded-lg bg-surface-container-low p-space-sm transition-all border border-outline-variant/30">
                        <summary className="cursor-pointer list-none flex items-center justify-between font-label-md text-label-md text-on-surface-variant group-hover:text-on-surface select-none">
                          <div className="flex items-center gap-2">
                            <span className="material-symbols-outlined text-[18px] text-primary transition-transform group-open:rotate-90">arrow_right</span>
                            <span className="font-medium text-on-surface">说说你的思路（可选）</span>
                            <span className="text-outline font-normal">—— 记录解题逻辑有助于强化记忆</span>
                          </div>
                          <span className="text-xs text-outline group-open:hidden">点击展开</span>
                        </summary>
                        <div className="mt-space-sm pt-space-xs flex flex-col gap-2">
                          <textarea className="w-full p-2.5 bg-surface-container-lowest rounded-md font-body-sm text-body-sm text-on-surface placeholder:text-outline-variant focus:outline-none focus:ring-1 focus:ring-primary shadow-xs resize-none border border-outline-variant/50" placeholder="写下你的审题思路或分析过程..." rows={2} />
                          <div className="flex justify-end">
                            <button className="px-3 py-1 rounded bg-surface-container-high text-on-surface-variant font-label-sm text-label-sm hover:bg-surface-variant transition-colors" type="button">保存想法</button>
                          </div>
                        </div>
                      </details>
                    </>
                  )}

                  <section className="bg-surface-container-lowest rounded-xl p-space-md shadow-sm flex flex-col gap-space-sm relative border border-outline-variant/40">
                    <div className="flex items-center justify-between pb-1">
                      <div className="flex items-center gap-2">
                        <div className="w-6 h-6 rounded-md bg-secondary-fixed flex items-center justify-center">
                          <span className="material-symbols-outlined text-secondary text-[16px]">psychology</span>
                        </div>
                        <h2 className="font-title-md text-title-md text-on-surface font-semibold">AI 伴学提示与答疑</h2>
                      </div>
                      <span className="font-label-sm text-label-sm text-outline">基于当前步骤 · 启发式引导（不提供现成答案）</span>
                    </div>
                    <div className="flex flex-col gap-space-sm pt-1 max-h-72 overflow-y-auto">
                      <div className="flex items-start gap-space-sm max-w-[95%]">
                        <div className="w-7 h-7 rounded-full bg-secondary-fixed/70 text-on-secondary-fixed flex items-center justify-center shrink-0 mt-0.5 text-xs font-semibold">径</div>
                        <div className="bg-surface-container-low rounded-xl rounded-tl-sm p-space-sm flex flex-col gap-1.5 shadow-xs text-on-surface border border-outline-variant/30">
                          <p className="font-body-md text-body-md leading-relaxed text-on-surface-variant">有疑惑可以随时点击“给我一点提示”，或在输入框写下你的思考，我会针对性启发你。</p>
                        </div>
                      </div>
                      {chat.map((turn, i) => (
                        turn.from === 'me' ? (
                          <div key={i} className="flex items-start gap-space-sm max-w-[85%] self-end flex-row-reverse">
                            <div className="w-7 h-7 rounded-full bg-primary text-on-primary flex items-center justify-center shrink-0 mt-0.5 text-xs font-medium">我</div>
                            <div className="bg-primary text-on-primary rounded-xl rounded-tr-sm p-space-sm shadow-sm text-sm leading-relaxed">{turn.text}</div>
                          </div>
                        ) : (
                          <div key={i} className="flex items-start gap-space-sm max-w-[90%]">
                            <div className="w-7 h-7 rounded-full bg-secondary-fixed/70 text-on-secondary-fixed flex items-center justify-center shrink-0 mt-0.5 text-xs font-semibold">径</div>
                            <div className="bg-surface-container-low rounded-xl rounded-tl-sm p-space-sm shadow-sm text-sm leading-relaxed text-on-surface">
                              {turn.text}
                              {turn.source && <div className="text-[11px] text-outline mt-1">{turn.source}</div>}
                            </div>
                          </div>
                        )
                      ))}
                    </div>
                    <div className="flex items-center gap-2 pt-1">
                      <div className="relative flex-1">
                        <input
                          className="w-full px-3.5 py-2 bg-surface rounded-lg font-body-sm text-body-sm text-on-surface placeholder:text-outline-variant focus:bg-surface-container-lowest focus:outline-none focus:ring-1 focus:ring-primary shadow-xs border border-outline-variant/40"
                          placeholder="哪里不太明白？说说你的困惑，我来一步步提示你..."
                          value={chatInput}
                          onChange={(e) => setChatInput(e.target.value)}
                          onKeyDown={(e) => { if (e.key === 'Enter' && !busy) void sendChat(); }}
                        />
                      </div>
                      <button className="px-4 py-2 rounded-lg bg-primary hover:bg-primary-container text-on-primary font-label-md text-label-md font-medium transition-colors flex items-center gap-1 shrink-0 shadow-xs disabled:opacity-50" onClick={sendChat} disabled={busy || !chatInput.trim()} type="button">
                        <span>发送</span>
                        <span className="material-symbols-outlined text-[15px]">send</span>
                      </button>
                    </div>
                  </section>
                </main>

                {/* ============ 右栏：学情依据（_2 原版结构，真实数据） ============ */}
                <aside className="flex flex-col gap-space-md w-full">
                  <div className="bg-surface-container-lowest rounded-xl p-space-md shadow-sm flex flex-col gap-space-sm border border-outline-variant/40">
                    <div className="flex items-center justify-between">
                      <span className="font-label-sm text-label-sm text-outline uppercase tracking-wider">核心知识点</span>
                      {currentMastery && currentMastery.estimate !== null && (
                        <span className="px-2 py-0.5 rounded-full bg-surface-container-low text-primary font-label-sm text-label-sm font-semibold">
                          估计掌握度 {Math.round(currentMastery.estimate * 100)}%
                        </span>
                      )}
                      {currentMastery && currentMastery.estimate === null && (
                        <span className="px-2 py-0.5 rounded-full bg-surface-container-low text-outline font-label-sm text-label-sm">尚未评估</span>
                      )}
                    </div>
                    {currentMastery ? (
                      <>
                        <div className="flex flex-col gap-1">
                          <h3 className="font-headline-sm text-headline-sm text-on-surface font-semibold">{currentMastery.title}</h3>
                          <p className="font-label-sm text-label-sm text-outline">初中数学 · 二次函数专题</p>
                        </div>
                        <div className="w-full bg-surface-container-high h-1.5 rounded-full overflow-hidden mt-1">
                          <div className="bg-primary h-full rounded-full" style={{ width: `${currentMastery.estimate === null ? 0 : Math.round(currentMastery.estimate * 100)}%` }} />
                        </div>
                        <div className="pt-1">
                          <span className="font-label-sm text-label-sm text-outline">
                            基于近期 {currentMastery.evidence_count} 道作答证据 · 状态：
                            {currentMastery.status === 'mastered' ? '已掌握' : currentMastery.status === 'needs_support' ? '需要巩固' : currentMastery.status === 'review_due' ? '复习到期' : currentMastery.status === 'unassessed' ? '尚未评估' : '正在学习'}
                          </span>
                        </div>
                      </>
                    ) : (
                      <div className="font-label-sm text-label-sm text-outline">开始任务后展示该知识点的证据投影。</div>
                    )}
                  </div>

                  <div className="bg-surface-container-lowest rounded-xl p-space-md shadow-sm flex flex-col gap-space-xs border border-outline-variant/40">
                    <div className="flex items-center gap-1.5 font-title-md text-title-md text-on-surface font-semibold">
                      <span className="material-symbols-outlined text-primary text-[18px]">alt_route</span>
                      <span>为什么这样安排</span>
                    </div>
                    <p className="font-body-sm text-body-sm text-on-surface-variant leading-relaxed">
                      {currentReason ?? '完成诊断后，规划器会给出每个节点的安排依据。'}
                    </p>
                  </div>

                  <div className="bg-surface-container-lowest rounded-xl p-space-md shadow-sm flex flex-col gap-space-xs border border-outline-variant/40">
                    <div className="flex items-center gap-1.5 font-title-md text-title-md text-on-surface font-semibold">
                      <span className="material-symbols-outlined text-primary text-[18px]">track_changes</span>
                      <span>本次学习目标</span>
                    </div>
                    <div className="flex items-start gap-2 pt-1">
                      <input className="w-4 h-4 rounded text-primary focus:ring-primary mt-1 accent-primary" disabled type="checkbox" />
                      <label className="font-body-sm text-body-sm text-on-surface leading-normal">
                        在不看完整答案的情况下，独立完成本题。
                        <span className="block text-outline font-label-sm mt-0.5">（独立答对才产生新的掌握证据）</span>
                      </label>
                    </div>
                  </div>
                </aside>
              </div>
            </div>
          </div>
        </div>
      </main>

      {/* 弹窗1：说说做题思路（_1 原版） */}
      <div className={`fixed inset-0 z-50 bg-black/40 items-center justify-center p-4 backdrop-blur-xs ${thinkOpen ? 'flex' : 'hidden'}`}>
        <div className="bg-surface-container-lowest rounded-2xl max-w-md w-full p-space-lg shadow-xl flex flex-col gap-space-md border border-outline-variant">
          <div className="flex items-center justify-between pb-space-xs border-b border-surface-container">
            <div className="flex items-center gap-2 text-primary font-title-lg text-title-lg font-bold">
              <span className="material-symbols-outlined">record_voice_over</span>
              <span>说说我的做题思路</span>
            </div>
            <button className="p-1 text-outline hover:text-on-surface transition-colors" onClick={() => setThinkOpen(false)} type="button">
              <span className="material-symbols-outlined">close</span>
            </button>
          </div>
          <p className="font-body-md text-body-md text-on-surface-variant">把你的思路写给伴学老师，会得到针对性的启发：</p>
          <textarea
            className="w-full p-space-sm rounded-lg bg-surface-container-low border border-outline-variant text-on-surface font-body-md focus:outline-none focus:ring-2 focus:ring-primary"
            onChange={(e) => setChatInput(e.target.value)}
            placeholder="例如：我看到括号里写着 -2，就以为横坐标也是 -2..."
            rows={3}
          />
          <div className="flex items-center justify-end gap-space-sm pt-1">
            <button className="px-space-md py-1.5 rounded-lg bg-surface-container text-on-surface-variant font-title-md text-title-md" onClick={() => setThinkOpen(false)} type="button">稍后再说</button>
            <button className="px-space-md py-1.5 rounded-lg bg-primary text-on-primary font-title-md text-title-md shadow-xs" onClick={() => { void sendChat(); setThinkOpen(false); }} type="button">发送给伴学老师</button>
          </div>
        </div>
      </div>

      {/* 弹窗2：诚信确认查看解析（_1 原版） */}
      <div className={`fixed inset-0 z-50 bg-black/40 items-center justify-center p-4 backdrop-blur-xs ${solutionModal ? 'flex' : 'hidden'}`}>
        <div className="bg-surface-container-lowest rounded-2xl max-w-md w-full p-space-lg shadow-xl flex flex-col gap-space-md border border-outline-variant">
          <div className="flex items-center justify-between pb-space-xs border-b border-surface-container">
            <div className="flex items-center gap-2 text-secondary font-title-lg text-title-lg font-bold">
              <span className="material-symbols-outlined">verified_user</span>
              <span>自主探究确认</span>
            </div>
            <button className="p-1 text-outline hover:text-on-surface transition-colors" onClick={() => setSolutionModal(false)} type="button">
              <span className="material-symbols-outlined">close</span>
            </button>
          </div>
          <div className="flex flex-col gap-2">
            <p className="font-body-md text-body-md text-on-surface leading-relaxed">你可以随时查看本题的完整推导过程。</p>
            <div className="p-3 rounded-lg bg-secondary-fixed/30 text-on-surface-variant text-body-sm leading-relaxed border border-secondary-container/40">
              <strong className="text-secondary font-semibold">诚信研习机制：</strong> 查看完整解析后，系统将为你推送一道同类变式题，以确认你真正掌握并能独立完成。</div>
          </div>
          <div className="flex items-center justify-end gap-space-sm pt-space-xs">
            <button className="px-space-md py-1.5 rounded-lg bg-surface-container text-on-surface-variant font-title-md text-title-md" onClick={() => setSolutionModal(false)} type="button">我再思考一下</button>
            <button className="px-space-md py-1.5 rounded-lg bg-secondary text-on-secondary font-title-md text-title-md shadow-xs" onClick={showSolution} disabled={busy} type="button">确认查看解析</button>
          </div>
        </div>
      </div>
    </div>
  );
}
