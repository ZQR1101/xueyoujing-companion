/** 学习记录：证据时间线（stitch 卡片风格；无数据空态） */
import { useCallback, useEffect, useState } from 'react';

import { ApiError } from '../api/client';
import { getMasteryHistory, getOverview } from '../api/endpoints';
import type { MasteryEntry } from '../api/types';
import { navigate } from '../lib/router';

interface HistoryData {
  concept_id: string;
  title: string;
  formula_version: string | null;
  points: {
    attempt_id: string | null;
    evidence_id: string | null;
    before: { estimate: number | null; status: string; evidence_count: number };
    after: { estimate: number | null; status: string; evidence_count: number };
    created_at: string;
  }[];
}

function fmt(v: number | null): string {
  return v === null ? '未评估' : `${Math.round(v * 100)}%`;
}

function statusText(status: string): string {
  return { mastered: '已掌握', developing: '进行中', needs_support: '需要巩固', unassessed: '尚未评估', review_due: '复习到期' }[status] ?? status;
}

export function RecordsMastery() {
  const [mastery, setMastery] = useState<MasteryEntry[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [history, setHistory] = useState<HistoryData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getOverview()
      .then((o) => {
        const entry = o.goals[0];
        if (!entry) { navigate('/profile'); return; }
        setMastery(entry.mastery);
        if (entry.mastery.length > 0) setSelected(entry.mastery[0].concept_id);
      })
      .catch((e: ApiError) => setError(e.message));
  }, []);

  const loadHistory = useCallback(async (conceptId: string) => {
    setHistory(null);
    try {
      setHistory(await getMasteryHistory(conceptId));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '加载记录失败');
    }
  }, []);

  useEffect(() => {
    if (selected) void loadHistory(selected);
  }, [selected, loadHistory]);

  if (error) {
    return (
      <div className="pl-64"><main className="w-full pt-16 min-h-screen bg-surface">
        <div className="px-gutter-desktop py-space-xl"><div className="p-space-md rounded-xl bg-error-container text-on-error-container font-body-md">{error}</div></div>
      </main></div>
    );
  }
  if (mastery === null) {
    return (
      <div className="pl-64"><main className="w-full pt-16 min-h-screen bg-surface">
        <div className="pt-space-3xl text-center text-outline font-body-md">正在加载学习记录…</div>
      </main></div>
    );
  }

  return (
    <div className="pl-64">
            <main className="w-full pt-16 min-h-screen bg-surface">
        <div className="w-full max-w-[900px] mx-auto px-gutter-desktop py-space-lg flex flex-col gap-space-md">
          <div className="pb-2 border-b border-outline-border/60">
            <h1 className="text-2xl font-bold tracking-tight text-on-surface font-serif">掌握度变化</h1>
            <p className="text-xs md:text-sm text-on-surface-variant mt-1">
              掌握变化基于有效证据逐条沉淀；可回放、可重建，辅助完成不进入曲线。
            </p>
          </div>

          <div className="flex items-center gap-1.5 flex-wrap">
            {mastery.map((m) => (
              <button
                key={m.concept_id}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-all ${selected === m.concept_id ? 'bg-primary text-on-primary border-primary shadow-sm' : 'bg-white text-on-surface-variant border-outline-border hover:text-on-surface hover:bg-surface-subtle'}`}
                onClick={() => setSelected(m.concept_id)}
                type="button"
              >
                {m.title} · {statusText(m.status)}
              </button>
            ))}
          </div>

          {history === null ? (
            <div className="pt-space-3xl text-center text-outline font-body-md">加载中…</div>
          ) : history.points.length === 0 ? (
            <div className="rounded-xl bg-surface-container-lowest border border-outline-border p-space-xl shadow-sm text-center py-space-3xl">
              <div className="w-14 h-14 mx-auto rounded-full bg-surface-container-low flex items-center justify-center text-primary mb-space-sm">
                <span className="material-symbols-outlined text-2xl">history_edu</span>
              </div>
              <h3 className="font-headline-sm text-headline-sm text-on-surface font-semibold mb-1">该知识点还没有记录</h3>
              <p className="font-body-sm text-body-sm text-outline mb-space-md">完成一次独立作答（首答、无提示）后，这里会出现第一条掌握证据。</p>
              <button className="px-space-lg py-space-sm rounded-lg bg-primary text-on-primary font-title-md text-title-md shadow-sm inline-flex items-center gap-2" onClick={() => navigate('/today')} type="button">
                去做今日任务<span className="material-symbols-outlined text-base">arrow_forward</span>
              </button>
            </div>
          ) : (
            <div className="p-5 md:p-6 rounded-xl bg-white border border-outline-border shadow-sm flex flex-col gap-4">
              <div className="flex items-center justify-between pb-3 border-b border-surface-subtle">
                <h2 className="text-base font-bold text-on-surface flex items-center gap-1.5">
                  <span className="material-symbols-outlined text-primary text-[19px]">timeline</span>
                  <span>{history.title} · 证据时间线</span>
                </h2>
                <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-primary-light text-primary border border-primary/20">公式版本 {history.formula_version ?? '—'}</span>
              </div>
              <div className="flex flex-col">
                {history.points.map((p, i) => {
                  const last = i === history.points.length - 1;
                  return (
                    <div className="relative flex items-start gap-4" key={i}>
                      {!last && <div className="absolute left-4 top-9 bottom-0 w-0.5 bg-outline-border" />}
                      <div className="relative z-10 w-8 h-8 rounded-full bg-status-mastered-bg text-status-mastered border border-status-mastered/30 flex items-center justify-center shrink-0 shadow-sm">
                        <span className="material-symbols-outlined text-[17px]">trending_up</span>
                      </div>
                      <div className="flex-1 pb-5">
                        <div className="text-sm text-on-surface">
                          {fmt(p.before.estimate)} → <strong className="text-primary">{fmt(p.after.estimate)}</strong>
                          {' · '}{p.after.evidence_count} 份证据 · {statusText(p.after.status)}
                        </div>
                        <div className="text-xs text-on-surface-variant mt-0.5 flex items-center gap-2 flex-wrap">
                          <span>{new Date(p.created_at).toLocaleString('zh-CN')}</span>
                          {p.evidence_id && <span className="px-1.5 py-0.5 rounded bg-surface-subtle text-[11px] border border-outline-border">证据 {p.evidence_id.slice(0, 8)}…</span>}
                          {p.attempt_id && <span className="px-1.5 py-0.5 rounded bg-surface-subtle text-[11px] border border-outline-border">作答 {p.attempt_id.slice(0, 8)}…</span>}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
              <div className="p-3 rounded-lg bg-surface-subtle text-xs text-on-surface-variant border border-outline-border/60">
                证据 ID 可追溯至具体作答；投影可由事件回放重建，辅助完成（提示/解析/重做）不会出现在本曲线。
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
