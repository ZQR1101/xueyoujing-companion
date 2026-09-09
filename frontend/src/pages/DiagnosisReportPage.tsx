/** T10-D 学情评估（诊断结论）：stitch stitch_ (7) 原版移植，交互三态齐全。
 *  真实数据：学生名、有效证据数、已测/未测知识点 ← GET /me/overview；
 *  「演示状态」为页面态切换（正常诊断/证据不足/诊断异常），默认态由真实证据数决定；
 *  诊断叙述文案为设计稿内容，后端推导叙述接口属后续工单。 */
import { useCallback, useEffect, useRef, useState } from 'react';

import { ApiError, currentStudent } from '../api/client';
import { createGoal, getOverview } from '../api/endpoints';
import type { OverviewData } from '../api/types';
import { navigate } from '../lib/router';

type DemoState = 'normal' | 'insufficient' | 'anomaly';

const SWITCH_BTN_BASE = 'px-space-sm py-1 rounded-full font-label-sm text-label-sm font-medium transition-all';
const SWITCH_BTN_IDLE = `${SWITCH_BTN_BASE} text-on-surface-variant hover:text-on-surface`;
const SWITCH_BTN_ACTIVE: Record<DemoState, string> = {
  normal: `${SWITCH_BTN_BASE} bg-surface-container-lowest text-primary shadow-sm`,
  insufficient: `${SWITCH_BTN_BASE} bg-surface-container-lowest text-secondary shadow-sm`,
  anomaly: `${SWITCH_BTN_BASE} bg-surface-container-lowest text-on-surface shadow-sm`,
};

/** 折叠面板「客观推导依据」四卡（设计稿文案） */
const RATIONALE_CARDS = [
  {
    icon: 'history_edu', iconClass: 'text-primary', title: '相关作答证据数量',
    body: '已综合参考本单元近期有效作答样本：基础点坐标直接代入正确率 100%，但在顶点形式逆向转换中呈现偏差信号。',
  },
  {
    icon: 'pattern', iconClass: 'text-secondary', title: '识别出的主要错误模式',
    body: '顶点横坐标在代数式内的正负符号映射反转（提取顶点坐标 (h, k) 时发生平移方向混淆），属于几何位移与代数公式结合时的典型卡点。',
  },
  {
    icon: 'psychology', iconClass: 'text-tertiary', title: '当前掌握情况判断',
    body: '基础二次函数解析式代数计算扎实完备；瓶颈仅集中在“图像顶点坐标与顶点式 (x-h)²”的双向推导，尚属局部单点问题。',
  },
  {
    icon: 'flag', iconClass: 'text-primary', title: '为什么需要安排补测',
    body: '排除偶发笔误可能。若本题一次作答正确，系统将认定掌握并直接解锁后续章节；若仍需辅导，将提供 3 分钟针对性图像拆解。',
  },
];

export function DiagnosisReportPage() {
  const [overview, setOverview] = useState<OverviewData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [demoState, setDemoState] = useState<DemoState>('normal');
  const [ringing, setRinging] = useState(false);
  const [rationaleOpen, setRationaleOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const rationaleRef = useRef<HTMLDivElement | null>(null);

  const load = useCallback(async () => {
    const data = await getOverview();
    setOverview(data);
    const entry = data.goals[0];
    const total = entry ? entry.mastery.reduce((s, m) => s + m.evidence_count, 0) : 0;
    setDemoState(!entry || total < 2 ? 'insufficient' : 'normal');
  }, []);

  useEffect(() => {
    load().catch((e: ApiError) => setError(e.message));
  }, [load]);

  if (error) {
    return (
      <div className="pl-64">
        <main className="w-full pt-16 min-h-screen bg-surface">
          <div className="max-w-[1240px] mx-auto px-gutter-desktop py-space-xl">
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
          <div className="p-space-xl text-center text-outline font-body-md">正在加载学情评估…</div>
        </main>
      </div>
    );
  }

  const entry = overview.goals[0];
  const mastery = entry?.mastery ?? [];
  const evidenceTotal = mastery.reduce((s, m) => s + m.evidence_count, 0);
  const assessed = mastery.filter((m) => m.evidence_count > 0);
  const unassessed = mastery.filter((m) => m.evidence_count === 0);
  const studentName = overview.student.display_name || currentStudent()?.display_name || '演示学生';

  const banner: Record<DemoState, { title: string; desc: string }> = {
    normal: {
      title: `AI 伴学诊断 · 已根据 ${evidenceTotal} 条相关作答证据完成分析`,
      desc: '本轮主要检查了：基础解析式、顶点平移和对称轴判定。分析已就绪，等待最终补测验证。',
    },
    insufficient: {
      title: `证据不足 · 仅有 ${assessed.length} 条作答记录，不足以做出稳定诊断`,
      desc: '系统建议完成 2 道基础诊断题以确立初始能力基准。',
    },
    anomaly: {
      title: '暂时无法完成深度学情分析，已启用基础自适应保障机制',
      desc: '作答数据已完整保留，不影响正常任务流。您可以重试或直接进入学习。',
    },
  };

  function triggerReDiagnose() {
    setRinging(true);
    setDemoState('normal');
    load().catch(() => undefined);
    setTimeout(() => setRinging(false), 700);
  }

  async function startSupplement() {
    if (entry) {
      navigate('/profile/diagnosis');
      return;
    }
    setCreating(true);
    try {
      await createGoal('quadratic', [], 25);
      navigate('/profile/diagnosis');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '创建目标失败');
      setCreating(false);
    }
  }

  return (
    <div className="pl-64">
      <main className="w-full pt-16 bg-surface min-h-screen">
        <div className="flex flex-col w-full">
          <div className="w-full max-w-[1240px] mx-auto px-gutter-desktop py-space-md flex flex-col gap-space-md">

            {/* 顶部元信息行：面包屑 + 演示状态切换 */}
            <div className="flex flex-wrap items-center justify-between gap-space-sm">
              <div className="flex items-center gap-space-xs">
                <span className="px-space-xs py-1 rounded bg-surface-container-high text-on-surface-variant font-label-sm text-label-sm">初中数学</span>
                <span className="text-outline text-label-sm">/</span>
                <span className="px-space-xs py-1 rounded bg-primary-fixed text-on-primary-fixed-variant font-label-sm text-label-sm font-semibold">二次函数与图像特征</span>
                <span className="text-outline text-label-sm">/</span>
                <span className="text-on-surface-variant font-label-sm text-label-sm">T10-D 学情评估</span>
              </div>
              <div className="flex items-center gap-2 bg-surface-container-highest px-2 py-1 rounded-full shadow-sm">
                <span className="font-label-sm text-label-sm text-outline pl-1.5 flex items-center gap-1 shrink-0">
                  <span className="material-symbols-outlined text-sm">tune</span>演示状态：
                </span>
                <div className="inline-flex rounded-full bg-surface-container p-0.5 whitespace-nowrap">
                  <button
                    className={demoState === 'normal' ? SWITCH_BTN_ACTIVE.normal : SWITCH_BTN_IDLE}
                    onClick={() => setDemoState('normal')}
                    type="button"
                  >正常诊断</button>
                  <button
                    className={demoState === 'insufficient' ? SWITCH_BTN_ACTIVE.insufficient : SWITCH_BTN_IDLE}
                    onClick={() => setDemoState('insufficient')}
                    type="button"
                  >证据不足</button>
                  <button
                    className={demoState === 'anomaly' ? SWITCH_BTN_ACTIVE.anomaly : SWITCH_BTN_IDLE}
                    onClick={() => setDemoState('anomaly')}
                    type="button"
                  >诊断异常</button>
                </div>
              </div>
            </div>

            {/* 页头 + 重新诊断 */}
            <div className="flex items-start justify-between gap-space-md pb-space-xs">
              <div className="flex flex-col gap-1">
                <div className="flex items-center gap-space-sm">
                  <h1 className="font-headline-lg text-headline-lg text-on-surface tracking-tight">AI 学情诊断</h1>
                  <span className="inline-flex items-center px-2 py-0.5 rounded-full font-label-sm text-label-sm bg-surface-container-low text-primary border-0 font-medium">
                    实时推导中
                  </span>
                </div>
                <p className="font-body-md text-body-md text-on-surface-variant">
                  根据你的作答表现，定位关键认知断点，智能匹配下一步自适应学习起点
                </p>
              </div>
              <button
                className="shrink-0 inline-flex items-center gap-1.5 px-space-md py-2 bg-surface-container-lowest text-primary hover:bg-surface-container-low rounded-lg font-title-md text-title-md transition-all shadow-sm active:scale-95 whitespace-nowrap"
                onClick={triggerReDiagnose}
                type="button"
              >
                <span className="material-symbols-outlined text-base">refresh</span>
                <span>重新诊断</span>
              </button>
            </div>

            {/* Agent 运行状态横幅 */}
            <div
              className={`w-full bg-surface-container-lowest rounded-xl p-space-sm shadow-sm flex items-center justify-between gap-space-md ${ringing ? 'ring-2 ring-primary transition-all' : ''}`}
              id="agent-status-banner"
            >
              <div className="flex items-center gap-space-sm min-w-0">
                <div className="relative flex items-center justify-center w-8 h-8 rounded-lg bg-primary-fixed text-primary shrink-0">
                  <span className="material-symbols-outlined text-lg">auto_awesome</span>
                  <span className="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-primary agent-step-pulse" />
                </div>
                <div className="flex flex-col min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-title-md text-title-md text-on-surface font-semibold truncate" id="agent-status-title">{banner[demoState].title}</span>
                    {demoState === 'normal' && (
                      <span className="hidden md:inline-flex px-2 py-0.2 rounded-full font-label-sm text-label-sm bg-primary-fixed text-primary font-medium">当前判断较明确</span>
                    )}
                  </div>
                  <span className="font-body-sm text-body-sm text-outline truncate" id="agent-status-desc">{banner[demoState].desc}</span>
                </div>
              </div>
              <div className="hidden sm:flex items-center gap-1 text-primary font-label-sm text-label-sm shrink-0 pr-1">
                <span className="material-symbols-outlined text-base">verified_user</span>
                <span>学术证据链闭环</span>
              </div>
            </div>

            {/* 五步因果管线（仅正常态显示） */}
            {demoState === 'normal' && (
              <div className="w-full bg-surface-container-lowest rounded-xl p-space-md shadow-sm" id="pipeline-container">
                <div className="flex items-center justify-between mb-space-sm">
                  <span className="font-label-sm text-label-sm text-outline uppercase tracking-wider font-semibold">诊断进行中</span>
                  <span className="font-label-sm text-label-sm text-primary font-medium">当前进度：正在确认是否需要补测</span>
                </div>
                <div className="grid grid-cols-5 gap-2 relative items-center">
                  <div className="flex flex-col gap-1 p-space-xs rounded-lg bg-surface-container-low transition-colors">
                    <div className="flex items-center justify-between">
                      <span className="w-6 h-6 rounded-full bg-primary text-on-primary flex items-center justify-center font-label-sm text-label-sm font-semibold"><span className="material-symbols-outlined text-sm">check</span></span>
                      <span className="font-label-sm text-label-sm text-primary font-medium">步骤 1</span>
                    </div>
                    <span className="font-title-md text-title-md text-on-surface font-medium truncate mt-1">观察作答证据</span>
                    <span className="font-label-sm text-label-sm text-outline truncate">已采纳 {evidenceTotal} 题样本</span>
                  </div>
                  <div className="flex flex-col gap-1 p-space-xs rounded-lg bg-surface-container-low transition-colors">
                    <div className="flex items-center justify-between">
                      <span className="w-6 h-6 rounded-full bg-primary text-on-primary flex items-center justify-center font-label-sm text-label-sm font-semibold"><span className="material-symbols-outlined text-sm">check</span></span>
                      <span className="font-label-sm text-label-sm text-primary font-medium">步骤 2</span>
                    </div>
                    <span className="font-title-md text-title-md text-on-surface font-medium truncate mt-1">识别学习卡点</span>
                    <span className="font-label-sm text-label-sm text-outline truncate">符号平移映射混淆</span>
                  </div>
                  <div className="flex flex-col gap-1 p-space-xs rounded-lg bg-surface-container-highest shadow-sm relative">
                    <div className="flex items-center justify-between">
                      <span className="w-6 h-6 rounded-full bg-primary-container text-on-primary flex items-center justify-center font-label-sm text-label-sm font-semibold agent-step-pulse">3</span>
                      <span className="px-1.5 py-0.2 rounded-full font-label-sm text-label-sm bg-secondary-fixed text-on-secondary-fixed font-bold">需 1 题检验</span>
                    </div>
                    <span className="font-title-md text-title-md text-primary font-semibold truncate mt-1">评估诊断充分性</span>
                    <span className="font-label-sm text-label-sm text-on-surface-variant truncate">排除偶发笔误</span>
                  </div>
                  <div className="flex flex-col gap-1 p-space-xs rounded-lg bg-surface-container opacity-80">
                    <div className="flex items-center justify-between">
                      <span className="w-6 h-6 rounded-full bg-surface-container-highest text-on-surface-variant flex items-center justify-center font-label-sm text-label-sm">4</span>
                      <span className="font-label-sm text-label-sm text-outline">步骤 4</span>
                    </div>
                    <span className="font-title-md text-title-md text-on-surface-variant font-medium truncate mt-1">生成针对性补测</span>
                    <span className="font-label-sm text-label-sm text-outline truncate">智能生成微题</span>
                  </div>
                  <div className="flex flex-col gap-1 p-space-xs rounded-lg bg-surface-container opacity-60">
                    <div className="flex items-center justify-between">
                      <span className="w-6 h-6 rounded-full bg-surface-container-highest text-on-surface-variant flex items-center justify-center font-label-sm text-label-sm">5</span>
                      <span className="font-label-sm text-label-sm text-outline">步骤 5</span>
                    </div>
                    <span className="font-title-md text-title-md text-on-surface-variant font-medium truncate mt-1">更新学习路径</span>
                    <span className="font-label-sm text-label-sm text-outline truncate">重排课时节奏</span>
                  </div>
                </div>
              </div>
            )}

            {/* 态一：正常诊断 */}
            {demoState === 'normal' && (
              <div className="flex flex-col gap-space-md" id="view-normal">

                {/* 核心结论卡 */}
                <div className="w-full bg-surface-container-lowest rounded-xl p-space-lg shadow-sm flex flex-col gap-space-md">
                  <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-2">
                      <span className="px-2.5 py-0.5 rounded-full font-label-sm text-label-sm bg-primary-fixed text-primary font-semibold">AI 诊断核心结论</span>
                      <span className="font-label-sm text-label-sm text-outline">初三数学 · 二次函数</span>
                    </div>
                    <h2 className="font-headline-md text-headline-md text-on-surface font-semibold tracking-tight mt-1">“你已经掌握基础代入，但在根据图像反推解析式时还需要进一步确认。”</h2>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-space-md pt-1">
                    <div className="flex flex-col p-space-md rounded-xl bg-[#FEF7EE] shadow-sm relative overflow-hidden">
                      <div className="absolute top-0 left-0 bottom-0 w-1.5 bg-[#D97736]" />
                      <div className="flex items-center gap-2 mb-space-xs pl-1">
                        <span className="material-symbols-outlined text-[#D97736]">saved_search</span>
                        <span className="font-title-md text-title-md font-bold text-[#D97736]">已观察到</span>
                      </div>
                      <p className="font-body-md text-body-md text-on-surface pl-1 leading-relaxed">顶点位置与解析式中的符号对应可能混淆。</p>
                    </div>
                    <div className="flex flex-col p-space-md rounded-xl bg-[#F2F6F9] shadow-sm relative overflow-hidden">
                      <div className="absolute top-0 left-0 bottom-0 w-1.5 bg-[#4A6B82]" />
                      <div className="flex items-center gap-2 mb-space-xs pl-1">
                        <span className="material-symbols-outlined text-[#4A6B82]">help_outline</span>
                        <span className="font-title-md text-title-md font-bold text-[#4A6B82]">仍需确认</span>
                      </div>
                      <p className="font-body-md text-body-md text-on-surface pl-1 leading-relaxed">你能否根据另一个图像独立写出解析式。</p>
                    </div>
                    <div className="flex flex-col p-space-md rounded-xl bg-[#EFF7F5] shadow-sm relative overflow-hidden">
                      <div className="absolute top-0 left-0 bottom-0 w-1.5 bg-[#2C6E63]" />
                      <div className="flex items-center gap-2 mb-space-xs pl-1">
                        <span className="material-symbols-outlined text-[#2C6E63]">forward</span>
                        <span className="font-title-md text-title-md font-bold text-[#2C6E63]">建议下一步</span>
                      </div>
                      <p className="font-body-md text-body-md text-on-surface pl-1 leading-relaxed">完成 1 道针对性补测题，确认是否需要加强“顶点式与图像映射”。</p>
                    </div>
                  </div>
                </div>

                {/* 推荐行动卡 */}
                <div className="w-full bg-surface-container-lowest rounded-xl p-space-md shadow-sm flex flex-col md:flex-row items-center justify-between gap-space-md bg-gradient-to-r from-surface-container-lowest via-surface-container-lowest to-surface-container-low">
                  <div className="flex flex-col gap-1.5 w-full md:w-auto">
                    <div className="flex items-center gap-2">
                      <span className="px-2.5 py-0.5 rounded-full font-label-sm text-label-sm bg-primary-fixed text-primary font-semibold flex items-center gap-1">
                        <span className="material-symbols-outlined text-xs">bolt</span>AI 针对性补测
                      </span>
                      <span className="font-label-sm text-label-sm text-outline">预计 2 分钟 · 仅 1 题</span>
                    </div>
                    <h3 className="font-title-lg text-title-lg text-on-surface font-semibold">建议先做一道补测题</h3>
                    <p className="font-body-md text-body-md text-on-surface-variant max-w-2xl">这道题用于确认你的错误是偶发失误，还是需要进一步巩固。</p>
                    <div className="inline-flex items-center gap-2 px-space-sm py-1 rounded bg-surface-container-high text-on-surface font-label-md text-label-md w-fit mt-0.5">
                      <span className="material-symbols-outlined text-primary text-sm">assignment</span>
                      <span>目标题目：根据图像顶点坐标快速求解二次函数解析式</span>
                    </div>
                  </div>
                  <div className="shrink-0 w-full md:w-auto flex flex-col items-end gap-1">
                    <button
                      className="w-full md:w-auto inline-flex items-center justify-center gap-space-sm px-space-xl py-3.5 bg-primary hover:bg-[#23584F] text-on-primary rounded-xl font-title-lg text-title-lg shadow-md hover:shadow-lg transition-all active:scale-[0.98] group whitespace-nowrap disabled:opacity-60"
                      disabled={creating}
                      onClick={startSupplement}
                      type="button"
                    >
                      <span>{creating ? '正在准备…' : '开始补测'}</span>
                      <span className="material-symbols-outlined text-lg group-hover:translate-x-1 transition-transform">arrow_forward</span>
                    </button>
                    <span className="font-label-sm text-label-sm text-outline self-center md:self-end">完成后，系统会根据你的新表现更新学习路径。</span>
                  </div>
                </div>

                {/* 推导依据折叠面板 */}
                <div className="w-full bg-surface-container-lowest rounded-xl shadow-sm overflow-hidden">
                  <button
                    className="w-full px-space-md py-space-sm flex items-center justify-between text-left hover:bg-surface-container transition-colors"
                    onClick={() => setRationaleOpen((v) => !v)}
                    type="button"
                  >
                    <div className="flex items-center gap-2">
                      <span className="material-symbols-outlined text-primary text-base">account_tree</span>
                      <span className="font-title-md text-title-md text-primary font-medium">为什么这样判断？ (点击展开客观推导依据)</span>
                    </div>
                    <span
                      className="material-symbols-outlined text-outline transition-transform duration-200"
                      id="collapse-icon"
                      style={{ transform: rationaleOpen ? 'rotate(180deg)' : 'rotate(0deg)' }}
                    >expand_more</span>
                  </button>
                  <div
                    ref={rationaleRef}
                    className={`custom-collapse-body overflow-hidden px-space-md pb-0 flex flex-col gap-space-md ${rationaleOpen ? 'opacity-100' : 'max-h-0 opacity-0'}`}
                    id="rationale-content"
                    style={{ maxHeight: rationaleOpen && rationaleRef.current ? `${rationaleRef.current.scrollHeight + 50}px` : '0px' }}
                  >
                    <div className="pt-space-xs pb-space-md grid grid-cols-1 md:grid-cols-2 gap-space-md">
                      {RATIONALE_CARDS.map((card) => (
                        <div className="p-space-sm rounded-lg bg-surface-container-low flex flex-col gap-1" key={card.title}>
                          <div className="flex items-center gap-1.5 font-label-md text-label-md text-on-surface font-semibold">
                            <span className={`material-symbols-outlined text-sm ${card.iconClass}`}>{card.icon}</span>
                            <span>{card.title}</span>
                          </div>
                          <p className="font-body-sm text-body-sm text-on-surface-variant">{card.body}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* 态二：证据不足 */}
            {demoState === 'insufficient' && (
              <div className="flex flex-col gap-space-md" id="view-insufficient">
                <div className="w-full bg-surface-container-lowest rounded-xl p-space-xl shadow-sm flex flex-col md:flex-row items-center justify-between gap-space-lg">
                  <div className="flex flex-col gap-space-xs max-w-2xl">
                    <div className="flex items-center gap-2">
                      <span className="px-2.5 py-0.5 rounded-full font-label-sm text-label-sm bg-secondary-fixed text-on-secondary-fixed font-bold">
                        样本采集中
                      </span>
                      <span className="font-label-sm text-label-sm text-outline">已录入 {assessed.length} / 需 3 条有效作答</span>
                    </div>
                    <h2 className="font-headline-md text-headline-md text-on-surface font-semibold">
                      目前仅收集到 {assessed.length} 条作答记录，不足以做出稳定诊断
                    </h2>
                    <p className="font-body-md text-body-md text-on-surface-variant leading-relaxed">
                      为了避免根据单次笔误仓促下结论，AI 伴学需要你完成 2 道基础诊断题，以完整建立当前章节认知模型，精准锁定薄弱项。
                    </p>
                    <div className="flex flex-wrap items-center gap-space-md mt-space-xs font-label-sm text-label-sm text-outline">
                      {assessed.slice(0, 1).map((m) => (
                        <span className="flex items-center gap-1" key={m.concept_id}>
                          <span className="material-symbols-outlined text-sm text-primary">check_circle</span>{m.title} (已完成)
                        </span>
                      ))}
                      {unassessed.slice(0, assessed.length ? 2 : 3).map((m) => (
                        <span className="flex items-center gap-1" key={m.concept_id}>
                          <span className="material-symbols-outlined text-sm text-outline">radio_button_unchecked</span>{m.title}待测
                        </span>
                      ))}
                      {!entry && (
                        <span className="flex items-center gap-1">
                          <span className="material-symbols-outlined text-sm text-outline">radio_button_unchecked</span>首次诊断待完成
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="shrink-0 w-full md:w-auto">
                    <button
                      className="w-full md:w-auto inline-flex items-center justify-center gap-space-sm px-space-xl py-3.5 bg-primary hover:bg-[#23584F] text-on-primary rounded-xl font-title-lg text-title-lg shadow-md transition-all active:scale-[0.98] whitespace-nowrap disabled:opacity-60"
                      disabled={creating}
                      onClick={startSupplement}
                      type="button"
                    >
                      <span>{creating ? '正在准备…' : '继续答题建立基准'}</span>
                      <span className="material-symbols-outlined text-lg">arrow_forward</span>
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* 态三：诊断异常 */}
            {demoState === 'anomaly' && (
              <div className="flex flex-col gap-space-md" id="view-anomaly">
                <div className="w-full bg-surface-container-lowest rounded-xl p-space-xl shadow-sm flex flex-col md:flex-row items-center justify-between gap-space-lg">
                  <div className="flex flex-col gap-space-xs max-w-2xl">
                    <div className="flex items-center gap-2">
                      <span className="px-2.5 py-0.5 rounded-full font-label-sm text-label-sm bg-surface-container-high text-on-surface-variant font-bold">
                        基础保护模式
                      </span>
                      <span className="font-label-sm text-label-sm text-outline">自适应引擎响应超时</span>
                    </div>
                    <h2 className="font-headline-md text-headline-md text-on-surface font-semibold">
                      暂时无法完成深度学情分析，已启用自适应保障机制
                    </h2>
                    <p className="font-body-md text-body-md text-on-surface-variant leading-relaxed">
                      请放心，你的所有作答数据与思考草稿均已安全留存。你可以立即尝试重新发起诊断，或先根据系统默认标准路径进行今日练习。
                    </p>
                    <span className="font-label-sm text-label-sm text-outline">
                      已为账号“{studentName}”保留现场作答参数快照，无需担心数据重复录入。
                    </span>
                  </div>
                  <div className="shrink-0 w-full md:w-auto flex flex-col sm:flex-row items-center gap-space-sm">
                    <button
                      className="w-full sm:w-auto inline-flex items-center justify-center gap-space-xs px-space-md py-3 bg-surface-container-high text-on-surface hover:bg-surface-variant rounded-xl font-title-md text-title-md transition-all"
                      onClick={triggerReDiagnose}
                      type="button"
                    >
                      <span className="material-symbols-outlined text-base">cached</span>
                      <span>重试分析</span>
                    </button>
                    <button
                      className="w-full sm:w-auto inline-flex items-center justify-center gap-space-xs px-space-lg py-3 bg-primary hover:bg-[#23584F] text-on-primary rounded-xl font-title-md text-title-md shadow-sm transition-all whitespace-nowrap"
                      onClick={() => navigate('/today')}
                      type="button"
                    >
                      <span>直接进入推荐学习</span>
                      <span className="material-symbols-outlined text-base">arrow_forward</span>
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* 底部安心说明 */}
            <div className="w-full flex items-center justify-center gap-1.5 py-2 text-outline font-label-sm text-label-sm">
              <span className="material-symbols-outlined text-base text-primary">info</span>
              <span>完成补测后，AI 会根据新的作答证据自动更新你的二次函数进阶路径</span>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
