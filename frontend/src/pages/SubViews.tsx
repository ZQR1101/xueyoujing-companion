/** 模块二级视图：薄弱知识点 / 路径调整记录 / 路径-任务清单 / 错题本 / 学习记录 / 学习反思 */
import { useCallback, useEffect, useState } from 'react';

import { ApiError } from '../api/client';
import {
  getOverview, getPath, getPlans, getTasks, getSession, getReflections, getSessionSummaryMetrics, saveReflection, queryRag, getMotivation, getLeaderboard, claimReward,
} from '../api/endpoints';
import type { MasteryEntry, PathData, TaskDto } from '../api/types';
import { navigate } from '../lib/router';

function Shell({ children, wide }: { children: React.ReactNode; wide?: boolean }) {
  return (
    <div className="pl-64">
      <main className="w-full pt-16 min-h-screen bg-surface">
        <div className={wide ? 'w-full max-w-[1280px] mx-auto px-gutter-desktop py-space-lg' : 'w-full max-w-[900px] mx-auto px-gutter-desktop py-space-lg'}>
          {children}
        </div>
      </main>
    </div>
  );
}

function Header({ title, sub }: { title: string; sub: string }) {
  return (
    <div className="pb-2 border-b border-outline-border/60 mb-space-md">
      <h1 className="text-2xl font-bold tracking-tight text-on-surface font-serif">{title}</h1>
      <p className="text-xs md:text-sm text-on-surface-variant mt-1">{sub}</p>
    </div>
  );
}

async function goalAndSession(): Promise<{ goalId: string | null; sessionId: string | null }> {
  const overview = await getOverview();
  const entry = overview.goals[0];
  if (!entry || !entry.latest_session) return { goalId: entry?.goal.id ?? null, sessionId: null };
  const detail = await getSession(entry.latest_session.id);
  return { goalId: entry.goal.id, sessionId: detail.session.id };
}

const STATUS_TEXT: Record<string, string> = {
  mastered: '已掌握', developing: '进行中', needs_support: '需要巩固', unassessed: '尚未评估', review_due: '复习到期', locked: '待解锁',
};

/* ---------------- 薄弱知识点 (/profile/weak) ---------------- */
export function WeakView() {
  const [rows, setRows] = useState<{ concept_id: string; title: string; status: string; estimate: number | null; evidence_count: number; reason: string }[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const overview = await getOverview();
        const entry = overview.goals[0];
        if (!entry) { navigate('/profile/diagnosis'); return; }
        const pathData: PathData = await getPath(entry.goal.id);
        const masteryMap = new Map<string, MasteryEntry>(entry.mastery.map((m) => [m.concept_id, m]));
        const weak = pathData.nodes.filter((n) => n.status === 'needs_support' || n.status === 'review_due' || n.status === 'locked' || n.status === 'developing');
        setRows(weak.map((n) => ({
          concept_id: n.concept_id, title: n.title, status: n.status,
          estimate: masteryMap.get(n.concept_id)?.estimate ?? null,
          evidence_count: masteryMap.get(n.concept_id)?.evidence_count ?? 0,
          reason: n.reason,
        })));
      } catch (e) {
        setError(e instanceof ApiError ? e.message : '加载失败');
      }
    })();
  }, []);

  if (error) return <Shell><div className="p-space-md rounded-xl bg-error-container text-on-error-container font-body-md">{error}</div></Shell>;
  return (
    <Shell wide>
      <Header title="薄弱知识点" sub="需要巩固、复习到期与前置未解锁的节点汇总，按规划器排序。" />
      {rows === null ? <div className="pt-space-3xl text-center text-outline font-body-md">加载中…</div>
        : rows.length === 0 ? (
          <div className="rounded-xl bg-surface-container-lowest border border-outline-border p-space-xl shadow-sm text-center py-space-3xl">
            <div className="w-14 h-14 mx-auto rounded-full bg-status-mastered-bg flex items-center justify-center text-status-mastered mb-space-sm">
              <span className="material-symbols-outlined text-2xl">verified</span>
            </div>
            <h3 className="font-headline-sm text-headline-sm text-on-surface font-semibold mb-1">当前没有薄弱节点</h3>
            <p className="font-body-sm text-body-sm text-outline mb-space-md">继续保持节奏，或做一轮诊断补测更多知识点。</p>
            <button className="px-space-lg py-space-sm rounded-lg bg-primary text-on-primary font-title-md text-title-md shadow-sm" onClick={() => navigate('/profile/diagnosis')} type="button">去诊断</button>
          </div>
        ) : (
          <div className="flex flex-col gap-space-xs">
            {rows.map((r) => (
              <div className={`p-space-md rounded-xl flex items-start gap-space-sm border ${r.status === 'locked' ? 'bg-surface-subtle border border-outline-border' : r.status === 'needs_support' || r.status === 'review_due' ? 'bg-secondary-light/40 border border-secondary-border/60' : 'bg-surface-container-lowest border border-outline-variant/50'}`} key={r.concept_id}>
                <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 ${r.status === 'locked' ? 'bg-white text-status-locked border border-outline-border' : r.status === 'needs_support' || r.status === 'review_due' ? 'bg-secondary-light text-secondary-accent border border-secondary-border' : 'bg-primary-fixed text-primary'}`}>
                  <span className="material-symbols-outlined text-[18px]">{r.status === 'locked' ? 'lock' : r.status === 'needs_support' || r.status === 'review_due' ? 'cached' : 'play_arrow'}</span>
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-title-md text-title-md text-on-surface font-semibold">{r.title}</span>
                    <span className={`px-2 py-0.5 rounded-full text-[11px] font-semibold ${r.status === 'locked' ? 'bg-surface-subtle text-status-locked border border-outline-border' : r.status === 'needs_support' || r.status === 'review_due' ? 'bg-secondary-light text-secondary-dark border border-secondary-border' : 'bg-surface-container text-primary'}`}>{STATUS_TEXT[r.status]}</span>
                    {r.estimate !== null && <span className="text-xs text-on-surface-variant">估计掌握度 {Math.round(r.estimate * 100)}%</span>}
                    <span className="text-xs text-outline">· {r.evidence_count} 条证据</span>
                  </div>
                  <p className="text-xs text-on-surface-variant mt-1">{r.reason}</p>
                </div>
                {r.status !== 'locked' && (
                  <button className="px-3 py-1.5 rounded-lg bg-primary text-on-primary text-xs font-medium hover:bg-primary-container shadow-sm shrink-0" onClick={() => navigate('/today')} type="button">去练习</button>
                )}
              </div>
            ))}
          </div>
        )}
    </Shell>
  );
}

/* ---------------- 路径调整记录 (/path/adjust) ---------------- */
export function AdjustView() {
  const [plans, setPlans] = useState<Awaited<ReturnType<typeof getPlans>>['plans'] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const { goalId } = await goalAndSession();
        if (!goalId) { navigate('/profile/diagnosis'); return; }
        setPlans((await getPlans(goalId)).plans);
      } catch (e) {
        setError(e instanceof ApiError ? e.message : '加载失败');
      }
    })();
  }, []);

  if (error) return <Shell><div className="p-space-md rounded-xl bg-error-container text-on-error-container font-body-md">{error}</div></Shell>;
  return (
    <Shell wide>
      <Header title="路径调整记录" sub="每次规划触发（诊断完成 / 有效证据变化 / 手动重算）都会产生一个新版本；顺序与节点状态无真正变化时不升版。" />
      {plans === null ? <div className="pt-space-3xl text-center text-outline font-body-md">加载中…</div>
        : plans.length === 0 ? (
          <div className="rounded-xl bg-surface-container-lowest border border-outline-border p-space-xl shadow-sm text-center py-space-3xl">
            <h3 className="font-headline-sm text-headline-sm text-on-surface font-semibold mb-1">还没有计划记录</h3>
            <p className="font-body-sm text-body-sm text-outline mb-space-md">完成首轮诊断后生成计划 v1。</p>
            <button className="px-space-lg py-space-sm rounded-lg bg-primary text-on-primary font-title-md text-title-md shadow-sm" onClick={() => navigate('/profile/diagnosis')} type="button">去诊断</button>
          </div>
        ) : (
          <div className="flex flex-col gap-space-md">
            {plans.map((p, i) => (
              <div className="p-4 md:p-5 rounded-xl bg-white border border-outline-border shadow-sm flex flex-col gap-3" key={p.id}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className={`px-2 py-0.5 rounded-full text-[11px] font-semibold ${i === 0 ? 'bg-primary text-on-primary' : 'bg-surface-subtle text-on-surface-variant border border-outline-border'}`}>v{p.version}</span>
                    <span className="text-sm font-semibold text-on-surface">{p.reason_code}</span>
                  </div>
                  <span className="text-xs text-outline">{new Date(p.created_at).toLocaleString('zh-CN')}</span>
                </div>
                <div className="text-xs text-on-surface-variant">{p.ordered_concept_ids.join(' → ')}</div>
              </div>
            ))}
          </div>
        )}
    </Shell>
  );
}

/* ---------------- 路径-任务清单 (/path/tasks) ---------------- */
export function PathTasksView() {
  const [tasks, setTasks] = useState<TaskDto[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const { goalId } = await goalAndSession();
        if (!goalId) { navigate('/profile/diagnosis'); return; }
        setTasks((await getTasks(goalId)).tasks);
      } catch (e) {
        setError(e instanceof ApiError ? e.message : '加载失败');
      }
    })();
  }, []);

  if (error) return <Shell><div className="p-space-md rounded-xl bg-error-container text-on-error-container font-body-md">{error}</div></Shell>;
  return (
    <Shell>
      <Header title="任务清单" sub="计划内的讲解 / 独立练习 / 复习验证任务，去今日任务中完成。" />
      {tasks === null ? <div className="pt-space-3xl text-center text-outline font-body-md">加载中…</div>
        : tasks.length === 0 ? (
          <div className="rounded-xl bg-surface-container-lowest border border-outline-border p-space-xl shadow-sm text-center py-space-3xl">
            <h3 className="font-headline-sm text-headline-sm text-on-surface font-semibold mb-1">还没有任务</h3>
            <p className="font-body-sm text-body-sm text-outline mb-space-md">先完成一轮诊断，规划器会按预算生成任务。</p>
            <button className="px-space-lg py-space-sm rounded-lg bg-primary text-on-primary font-title-md text-title-md shadow-sm" onClick={() => navigate('/profile/diagnosis')} type="button">去诊断</button>
          </div>
        ) : (
          <div className="flex flex-col gap-space-xs">
            {tasks.map((t) => (
              <div className="p-space-md rounded-xl bg-white border border-outline-border shadow-xs flex items-center justify-between gap-3" key={t.id}>
                <div className="flex items-center gap-3 min-w-0">
                  <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 ${t.status === 'completed' ? 'bg-status-mastered-bg text-status-mastered' : t.status === 'active' ? 'bg-primary text-on-primary' : 'bg-surface-container text-outline'}`}>
                    <span className="material-symbols-outlined text-[17px]">{t.status === 'completed' ? 'check' : t.status === 'active' ? 'play_arrow' : t.status === 'cancelled' ? 'close' : 'menu_book'}</span>
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm font-semibold text-on-surface">{t.concept_id} · {t.type === 'lesson' ? '讲解' : t.type === 'practice' ? '独立练习' : '复习验证'}</div>
                    <div className="text-xs text-outline">{t.estimated_minutes} 分钟 · {t.status === 'completed' ? '已完成' : t.status === 'active' ? '进行中' : t.status === 'cancelled' ? '已调整' : '待开始'}</div>
                  </div>
                </div>
                {t.status !== 'completed' && t.status !== 'cancelled' && (
                  <button className="px-3 py-1.5 rounded-lg bg-primary text-on-primary text-xs font-medium hover:bg-primary-container shadow-sm shrink-0" onClick={() => navigate('/today')} type="button">去完成</button>
                )}
              </div>
            ))}
          </div>
        )}
    </Shell>
  );
}

/* ---------------- 错题本 (/today/mistakes) ---------------- */
export function MistakesView() {
  const [items, setItems] = useState<Awaited<ReturnType<typeof getOverview>>['recent_evidence'] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const overview = await getOverview();
        if (!overview.goals[0]) { navigate('/profile/diagnosis'); return; }
        setItems(overview.recent_evidence.filter((e) => e.score === 0));
      } catch (e) {
        setError(e instanceof ApiError ? e.message : '加载失败');
      }
    })();
  }, []);

  if (error) return <Shell><div className="p-space-md rounded-xl bg-error-container text-on-error-container font-body-md">{error}</div></Shell>;
  return (
    <Shell>
      <Header title="错题本" sub="近期答错记录：错答本身计入证据，辅助完成不重复记录。" />
      {items === null ? <div className="pt-space-3xl text-center text-outline font-body-md">加载中…</div>
        : items.length === 0 ? (
          <div className="rounded-xl bg-surface-container-lowest border border-outline-border p-space-xl shadow-sm text-center py-space-3xl">
            <div className="w-14 h-14 mx-auto rounded-full bg-surface-container-low flex items-center justify-center text-primary mb-space-sm">
              <span className="material-symbols-outlined text-2xl">bookmark</span>
            </div>
            <h3 className="font-headline-sm text-headline-sm text-on-surface font-semibold mb-1">暂无错题</h3>
            <p className="font-body-sm text-body-sm text-outline mb-space-md">新错题会自动出现在这里，可回到今日任务继续巩固。</p>
            <button className="px-space-lg py-space-sm rounded-lg bg-primary text-on-primary font-title-md text-title-md shadow-sm" onClick={() => navigate('/today')} type="button">去今日任务</button>
          </div>
        ) : (
          <div className="flex flex-col gap-space-xs">
            {items.map((e) => (
              <div className="p-space-md rounded-xl bg-white border border-outline-border shadow-xs flex items-center gap-3" key={e.id}>
                <div className={`w-2 h-2 rounded-full shrink-0 ${e.eligible ? 'bg-secondary' : 'bg-outline-variant'}`} />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-on-surface">{e.concept_id} · 答错{e.eligible ? '（计入掌握证据）' : `（不计入：${e.exclusion_reason ?? ''}）`}</div>
                  <div className="text-xs text-outline">{new Date(e.created_at).toLocaleString('zh-CN')} · 题族 {e.family_id}</div>
                </div>
                <button className="px-3 py-1.5 rounded-lg bg-surface-subtle text-on-surface-variant border border-outline-border text-xs font-medium hover:bg-surface-muted shrink-0" onClick={() => navigate('/today')} type="button">再练一次</button>
              </div>
            ))}
          </div>
        )}
    </Shell>
  );
}

/* ---------------- 学习记录 (/records) ---------------- */
export function RecordsHome() {
  const [items, setItems] = useState<Awaited<ReturnType<typeof getOverview>>['recent_evidence'] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const overview = await getOverview();
        if (!overview.goals[0]) { navigate('/profile/diagnosis'); return; }
        setItems(overview.recent_evidence);
      } catch (e) {
        setError(e instanceof ApiError ? e.message : '加载失败');
      }
    })();
  }, []);

  if (error) return <Shell><div className="p-space-md rounded-xl bg-error-container text-on-error-container font-body-md">{error}</div></Shell>;
  return (
    <Shell>
      <Header title="学习记录" sub="全部近期作答轨迹（含辅助完成），掌握曲线见「掌握度变化」。" />
      {items === null ? <div className="pt-space-3xl text-center text-outline font-body-md">加载中…</div>
        : items.length === 0 ? (
          <div className="rounded-xl bg-surface-container-lowest border border-outline-border p-space-xl shadow-sm text-center py-space-3xl">
            <h3 className="font-headline-sm text-headline-sm text-on-surface font-semibold mb-1">还没有作答记录</h3>
            <p className="font-body-sm text-body-sm text-outline mb-space-md">完成一次独立作答后，这里会留下可追溯的证据链。</p>
            <button className="px-space-lg py-space-sm rounded-lg bg-primary text-on-primary font-title-md text-title-md shadow-sm" onClick={() => navigate('/profile/diagnosis')} type="button">去诊断</button>
          </div>
        ) : (
          <div className="flex flex-col gap-space-xs">
            {items.map((e) => (
              <div className="p-space-md rounded-xl bg-white border border-outline-border shadow-xs flex items-center gap-3" key={e.id}>
                <div className={`w-2 h-2 rounded-full shrink-0 ${e.eligible ? 'bg-primary' : 'bg-outline-variant'}`} />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-on-surface">{e.concept_id} · {e.score === 1 ? '答对' : '答错'}</div>
                  <div className="text-xs text-outline">{new Date(e.created_at).toLocaleString('zh-CN')} · {e.eligible ? '独立证据' : `辅助完成（${e.exclusion_reason ?? ''}）`} · 题族 {e.family_id}</div>
                </div>
                <span className="text-xs text-outline shrink-0">证据 {e.id.slice(0, 8)}…</span>
              </div>
            ))}
          </div>
        )}
    </Shell>
  );
}

/* ---------------- 学习反思 (/records/reflection) ---------------- */
export function ReflectionView() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [list, setList] = useState<{ text: string; created_at: string }[]>([]);
  const [metrics, setMetrics] = useState<{ study_seconds: number; completed_task_count: number; independent_answer_count: number; new_eligible_evidence_count: number } | null>(null);
  const [text, setText] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const { goalId, sessionId: sid } = await goalAndSession();
    if (!goalId || !sid) { navigate('/profile/diagnosis'); return; }
    setSessionId(sid);
    const [reflections, summaryMetrics] = await Promise.all([getReflections(sid), getSessionSummaryMetrics(sid)]);
    setList(reflections.reflections);
    setMetrics(summaryMetrics);
  }, []);

  useEffect(() => { load().catch((e: ApiError) => setError(e.message)); }, [load]);

  async function save() {
    if (!sessionId || !text.trim()) return;
    setSaving(true); setError(null);
    try {
      const version = (await getSession(sessionId)).session.version;
      await saveReflection(sessionId, text.trim(), version);
      setText('');
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '保存失败');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Shell>
      <Header title="今天学得怎么样？" sub="AI 根据你的作答、提示使用和迁移练习，整理了这次学习过程与认知动态。" />
      <div className="mb-space-md rounded-r-xl border-l-4 border-primary bg-primary-light p-space-sm text-body-sm text-on-surface-variant">
        <strong className="text-on-surface">基于跨会话记忆的个性化衔接：</strong> 下次学习时，系统会从这里无缝继续；辅助完成不会被记作独立掌握。
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-space-sm mb-space-md">
        {[
          ['学习时长', String(Math.floor((metrics?.study_seconds ?? 0) / 60)), '分钟'],
          ['完成任务', String(metrics?.completed_task_count ?? 0), '项'],
          ['独立作答', String(metrics?.independent_answer_count ?? 0), '题'],
          ['新增有效证据', String(metrics?.new_eligible_evidence_count ?? 0), '条'],
        ].map(([label,value,unit]) => (
          <div className="rounded-xl bg-white border border-outline-border p-space-md shadow-sm" key={label}>
            <div className="font-label-sm text-label-sm text-outline">{label}</div>
            <div className="mt-1 text-2xl font-semibold text-on-surface">{value}<span className="ml-1 text-xs font-normal text-on-surface-variant">{unit}</span></div>
          </div>
        ))}
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-space-md mb-space-md">
        <section className="lg:col-span-3 rounded-xl bg-white border border-outline-border p-space-lg shadow-sm">
          <h2 className="font-headline-md text-headline-md text-on-surface font-semibold border-b border-outline-border/60 pb-space-sm">AI 学习小结</h2>
          <div className="grid sm:grid-cols-2 gap-space-md mt-space-md">
            <div><h3 className="font-title-md text-title-md text-primary font-semibold">已掌握基础</h3><p className="font-body-md text-body-md text-on-surface-variant mt-1">完成独立首答后，这里会记录有真实证据支持的基础。</p></div>
            <div><h3 className="font-title-md text-title-md text-secondary font-semibold">仍需巩固</h3><p className="font-body-md text-body-md text-on-surface-variant mt-1">提示或解析后完成的内容，会保留为待验证线索。</p></div>
          </div>
          <div className="mt-space-md rounded-lg bg-surface-container-low p-space-sm font-body-sm text-on-surface-variant">本次学习特点：系统只依据真实作答事件更新记忆，不会把模型生成文本当作掌握度。</div>
        </section>
        <section className="lg:col-span-2 rounded-xl bg-white border border-outline-border p-space-lg shadow-sm">
          <h2 className="font-title-lg text-title-lg text-on-surface font-semibold">下一次学习建议</h2>
          <p className="font-body-md text-body-md text-on-surface-variant mt-space-sm">沿当前有效路径继续，优先完成未完成任务并验证仍不稳定的知识点。</p>
          <button className="mt-space-md px-space-md py-space-sm rounded-lg bg-primary text-on-primary font-title-md text-title-md" onClick={() => navigate('/today')} type="button">查看今日任务 <span className="material-symbols-outlined text-sm align-middle">arrow_forward</span></button>
        </section>
      </div>
      <section className="rounded-xl bg-white border border-outline-border p-space-lg shadow-sm mb-space-md">
        <h2 className="font-title-lg text-title-lg text-on-surface font-semibold mb-space-sm">写下你的反思</h2>
        <p className="font-body-sm text-body-sm text-on-surface-variant mb-space-sm">学生自述只作为辅助上下文，不会单独改变掌握度。</p>
      {error && <div className="p-space-sm rounded-lg bg-error-container text-on-error-container font-body-md mb-space-md">{error}</div>}
      <div className="p-space-lg rounded-xl bg-white border border-outline-border shadow-sm flex flex-col gap-space-sm mb-space-md">
        <textarea className="w-full p-space-sm rounded-lg bg-surface-container-low border border-outline-variant text-on-surface font-body-md focus:outline-none focus:ring-2 focus:ring-primary resize-none" placeholder="例如：今天搞懂了 (-2)² 与 -2² 的区别…" rows={3} value={text} onChange={(e) => setText(e.target.value)} />
        <div className="flex justify-end">
          <button className="px-space-md py-1.5 rounded-lg bg-primary text-on-primary font-title-md text-title-md shadow-xs disabled:opacity-50" disabled={saving || !text.trim()} onClick={save} type="button">保存反思</button>
        </div>
      </div>
      </section>
      <div className="flex flex-col gap-space-md">
        {list.map((r, i) => (
          <div className="p-space-md rounded-xl bg-white border border-outline-border shadow-xs flex flex-col gap-1" key={i}>
            <span className="font-body-md text-body-md text-on-surface leading-relaxed">{r.text}</span>
            <span className="font-label-sm text-label-sm text-outline">{new Date(r.created_at).toLocaleString('zh-CN')}</span>
          </div>
        ))}
        {list.length === 0 && <div className="text-center text-outline font-body-sm py-space-lg">还没有反思记录。</div>}
      </div>
    </Shell>
  );
}

/** T10 知识点全景（占位）：页面属后续工单交付，当前保持信息架构完整。 */
export function KnowledgeMapView() {
  const [path, setPath] = useState<PathData | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { getOverview().then((o) => o.goals[0] ? getPath(o.goals[0].goal.id).then(setPath) : null).catch((e: ApiError) => setError(e.message)); }, []);
  if (error) return <Shell><Header title="知识点全景" sub="以先修关系呈现整章知识图谱与你的掌握状态。" /><div className="p-space-md rounded-xl bg-error-container text-on-error-container">{error}</div></Shell>;
  if (!path) return <Shell><Header title="知识点全景" sub="以先修关系呈现整章知识图谱与你的掌握状态。" /><div className="py-space-3xl text-center text-outline">正在加载知识点全景…</div></Shell>;
  return (
    <Shell wide>
      <Header title="知识点全景" sub="以先修关系呈现整章知识图谱与你的掌握状态。" />
      <div className="grid grid-cols-1 md:grid-cols-2 gap-space-md">
        {path.nodes.map((node) => (
          <article className={`p-space-lg rounded-xl bg-white border shadow-sm ${node.status === 'locked' ? 'border-outline-border opacity-70' : 'border-outline-border'}`} key={node.concept_id}>
            <div className="flex items-start justify-between gap-2"><div className="flex items-center gap-2"><span className="material-symbols-outlined text-primary">{node.status === 'locked' ? 'lock' : node.status === 'mastered' ? 'check_circle' : 'radio_button_unchecked'}</span><h2 className="font-title-lg text-title-lg text-on-surface font-semibold">{node.title}</h2></div><span className="px-2 py-0.5 rounded-full bg-primary-light text-primary font-label-sm text-label-sm">{node.status === 'mastered' ? '已掌握' : node.status === 'locked' ? '未解锁' : node.status === 'unassessed' ? '尚未评估' : '进行中'}</span></div>
            <p className="mt-space-sm font-body-md text-body-md text-on-surface-variant">{node.reason}</p>
            {node.tasks.length > 0 && <p className="mt-space-sm font-label-sm text-label-sm text-outline">当前任务 {node.tasks.length} 项 · {node.tasks[0].estimated_minutes} 分钟</p>}
          </article>
        ))}
      </div>
    </Shell>
  );
}

export function RagView() {
  const [q, setQ] = useState('二次函数顶点式中的符号如何对应？');
  const [data, setData] = useState<any>(null); const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null);
  async function run() { setBusy(true); setError(null); try { setData(await queryRag(q)); } catch (e) { setError(e instanceof ApiError ? e.message : '检索失败，请稍后重试。'); } finally { setBusy(false); } }
  return <Shell wide><Header title="这道题，换一种方式讲给你听" sub="Agentic RAG 从课程资料中找到适合你的解释，并标注出处。" /><div className="rounded-xl bg-white border border-outline-border p-space-md shadow-sm"><textarea className="w-full rounded-lg border border-outline-border bg-surface-container-low p-space-sm" rows={3} value={q} onChange={e => setQ(e.target.value)} /><button className="mt-space-sm px-space-md py-space-sm rounded-lg bg-primary text-on-primary" onClick={run} disabled={busy}>{busy ? '正在检索…' : '检索课程资料'}</button>{error && <div className="mt-space-sm rounded-lg bg-error-container p-space-sm text-on-error-container">{error}</div>}</div>{data && <div className="grid grid-cols-1 xl:grid-cols-12 gap-space-md mt-space-md"><article className="xl:col-span-7 rounded-xl bg-white border border-outline-border p-space-lg shadow-sm"><h2 className="font-headline-md text-headline-md font-semibold">AI 概念深度讲解</h2><p className="mt-space-md whitespace-pre-wrap text-body-md leading-relaxed">{data.content || data.safe_message || '暂时没有可生成的讲解。'}</p></article><aside className="xl:col-span-5 rounded-xl bg-white border border-outline-border p-space-lg shadow-sm"><h2 className="font-title-lg text-title-lg font-semibold">资料来源（{(data.sources ?? []).length} 条）</h2>{(data.sources ?? []).map((s: any) => <div className="mt-space-sm p-space-sm rounded-lg bg-surface-container-low" key={s.source_id}><b>{s.title}</b><p className="text-body-sm mt-1">{s.excerpt}</p><span className="text-label-sm text-primary">来源 {s.source_id} · 相关度 {s.score}</span></div>)}</aside></div>}</Shell>;
}

export function MotivationView() {
  const [data, setData] = useState<any>(null); const [board, setBoard] = useState<any[]>([]); const [error, setError] = useState<string | null>(null);
  useEffect(() => { Promise.all([getMotivation(), getLeaderboard()]).then(([m, b]) => { setData(m); setBoard(b.entries ?? b.leaderboard ?? b.items ?? []); }).catch((e) => setError(e.message)); }, []);
  if (error) return <Shell><div className="p-4 rounded-xl bg-error-container text-on-error-container">{error}</div></Shell>;
  if (!data) return <Shell><div className="text-outline">正在加载成就数据…</div></Shell>;
  const earned = data.badges ?? [], rewards = data.rewards ?? [];
  const catalog = ['第一条证据','任务完成者','三日坚持','迁移思考','反思记录','稳定复习','五日坚持','七日坚持','十四日坚持','首次突破','知识点掌握','三点掌握','章节探索者','路径践行者','认真订正','独立思考','少提示挑战','迁移挑战','反思习惯','学习规划师','早起研习','专注时刻','进步轨迹','坚持成长','研习里程碑'];
  const badges = catalog.map((name, i) => { const id = ['first_evidence','task_runner','three_day_streak'][i] ?? `badge_${i+1}`; const found = earned.find((b:any) => b.id === id); return found ?? { id, name, locked: true, reason: '完成对应真实学习要求后解锁' }; });
  const badgeMeta: Record<string, {icon:string; tone:string; ring:string; hint:string}> = { first_evidence: {icon:'verified',tone:'from-emerald-400 to-teal-700 text-white',ring:'ring-emerald-200',hint:'完成首次真实作答'}, task_runner:{icon:'task_alt',tone:'from-amber-300 to-orange-600 text-white',ring:'ring-amber-200',hint:'完成 3 项学习任务'}, three_day_streak:{icon:'local_fire_department',tone:'from-orange-400 to-rose-600 text-white',ring:'ring-orange-200',hint:'连续学习 3 天'} };
  return <Shell wide><Header title="你的学习成就" sub="每一次真实作答、任务完成和持续学习，都会沉淀为可追踪的学习成就。" /><div className="rounded-xl bg-primary text-white p-5 mb-6"><div className="flex justify-between"><span>{data.message}</span><span className="font-semibold">下一阶段还需 {data.next_reward?.points_needed ?? 0} 分</span></div><div className="h-2 bg-white/25 rounded-full mt-4"><div className="h-2 bg-white rounded-full" style={{width:`${Math.min(100, ((data.points ?? 0)%30)/30*100)}%`}} /></div></div><div className="grid sm:grid-cols-4 gap-3 mb-6">{[['当前积分', data.points ?? 0, '分'], ['成就等级', data.level_name ?? `Lv.${data.level ?? 1}`, ''], ['连续学习', data.streak_days ?? data.streak ?? 0, '天'], ['已获徽章', earned.length, ' / 25 枚']].map(([l,v,u]) => <div className="bg-white border border-outline-border rounded-xl p-4" key={String(l)}><div className="text-sm text-on-surface-variant">{l}</div><div className="text-2xl font-semibold text-primary mt-2">{v}<span className="text-sm ml-1">{u}</span></div></div>)}</div><div className="grid lg:grid-cols-[1fr_320px] gap-6"><section className="bg-white border border-outline-border rounded-xl p-5"><h2 className="text-xl font-serif font-semibold mb-4">学习徽章</h2><div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3.5">{badges.length ? badges.map((b:any) => { const m=badgeMeta[b.id] ?? {icon:'workspace_premium',tone:'from-sky-300 to-blue-600 text-white',ring:'ring-sky-200',hint:b.reason ?? '完成对应学习要求'}; return <div key={b.id ?? b.name} className="group relative bg-surface-container-lowest border border-outline-border rounded-2xl p-3 flex flex-col items-center text-center cursor-help min-h-[150px]"><div className="relative mx-auto w-20 h-[76px] transition-transform duration-200 group-hover:-translate-y-1 group-hover:scale-105"><div className={`absolute left-1/2 -translate-x-1/2 top-0 w-16 h-16 rounded-full bg-gradient-to-br ${m.tone} ring-4 ${m.ring} shadow-lg flex items-center justify-center`}><span className="material-symbols-outlined text-3xl drop-shadow">{m.icon}</span></div><div className="absolute bottom-0 left-1/2 -translate-x-1/2 flex gap-1"><i className="w-4 h-7 bg-current opacity-70 -skew-x-12 rounded-sm" /><i className="w-4 h-7 bg-current opacity-50 skew-x-12 rounded-sm" /></div></div><div className="text-sm font-semibold mt-1 truncate">{b.name}</div><div className="pointer-events-none absolute z-10 left-1/2 -translate-x-1/2 bottom-full mb-3 w-52 rounded-xl bg-ink-900 text-white text-xs p-3 text-left opacity-0 group-hover:opacity-100 transition-opacity shadow-xl"><div className="font-semibold mb-1">{b.name}</div>{m.hint}</div></div> }) : <p className="text-on-surface-variant">完成真实学习事件后解锁徽章。</p>}</div><h2 className="text-xl font-serif font-semibold mt-7 mb-4">可领取奖励</h2>{rewards.length ? rewards.map((r:any) => <div key={r.reward_id ?? r.id} className="flex items-center justify-between border-b border-outline-border py-3"><div><div className="font-medium">{r.name}</div><div className="text-sm text-on-surface-variant">{r.reason ?? '完成学习目标即可领取'}</div></div><button disabled={r.claimed} onClick={() => claimReward(r.reward_id ?? r.id).then(() => getMotivation().then(setData))} className="px-3 py-1.5 rounded-lg bg-primary text-white disabled:bg-surface-container">{r.claimed ? '已领取' : '领取'}</button></div>) : <p className="text-on-surface-variant">暂无可领取奖励，继续保持学习节奏。</p>}</section><aside className="bg-white border border-outline-border rounded-xl p-5"><h2 className="text-xl font-serif font-semibold mb-4">学习同行榜</h2>{board.length ? board.slice(0,8).map((x:any,i) => <div className="flex justify-between py-2 border-b border-outline-border/60" key={x.student_id ?? i}><span>#{x.rank ?? i+1} {x.display_name ?? x.nickname ?? '同行同学'}</span><span className="text-primary font-semibold">{x.points ?? x.score ?? 0} 分</span></div>) : <p className="text-on-surface-variant">完成一次真实学习任务后，这里会出现你的同行榜位置。</p>}</aside></div></Shell>;
}



