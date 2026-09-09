/** 统一顶栏：stitch _1 原版移植（SVG 徽标 + 导航 + 课程章 + 学生章） */
import { useEffect, useState } from 'react';
import { currentStudent, getRuntimeStatus, type RuntimeStatus } from '../api/client';
import { useRoute } from '../lib/router';

const NAV = [
  { path: '/profile', label: '我的学情', key: 'profile' },
  { path: '/path', label: '当前路径', key: 'path' },
  { path: '/today', label: '今日任务', key: 'today' },
  { path: '/records', label: '学习记录', key: 'records' },
];

export function TopBar() {
  const route = useRoute();
  const student = currentStudent();
  const activeKey = route.parts[0] ?? 'profile';
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null);
  const [backendOffline, setBackendOffline] = useState(false);

  useEffect(() => {
    let active = true;
    getRuntimeStatus()
      .then((result) => {
        if (active) setRuntime(result);
      })
      .catch(() => {
        if (active) setBackendOffline(true);
      });
    return () => { active = false; };
  }, []);

  const runtimeLabel = backendOffline
    ? '后端未连接'
    : runtime?.llm.provider === 'mock'
      ? 'Mock · 可重复演示'
      : runtime?.llm.configured
        ? `${runtime.llm.model_id ?? '在线模型'} · 规则回退`
        : runtime
          ? '模型未配置 · 规则回退'
          : '系统预检中';

  return (
    <header className="fixed top-0 left-0 w-full h-16 z-50 bg-surface-container-lowest border-b border-surface-variant/80">
      <div className="w-full max-w-[1440px] mx-auto h-16 px-gutter-desktop flex items-center justify-between gap-space-lg">
        <div className="flex items-center gap-space-md shrink-0">
          <a
            className="h-10 flex items-center shrink-0 hover:opacity-95 transition-opacity"
            href="#/profile"
            title="学有所径"
          >
            <svg className="h-9 w-auto" fill="none" height={40} viewBox="0 0 170 44" width={154} xmlns="http://www.w3.org/2000/svg">
              <g>
                <rect fill="#2C6E63" height={32} rx={8} width={32} x={2} y={6} />
                <path d="M10 27C14 27 14 15 18 15C22 15 22 23 26 23" stroke="#FFFFFF" strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} />
                <circle cx={26} cy={15} fill="#E28743" r={2.5} />
                <path d="M10 15L13 15" stroke="#A3D9C9" strokeLinecap="round" strokeWidth={2} />
              </g>
              <text fill="#1A2725" fontFamily="-apple-system, BlinkMacSystemFont, 'PingFang SC', 'Noto Serif SC', sans-serif" fontSize={17} fontWeight={700} letterSpacing={0.5} x={42} y={27}>学有所径</text>
              <text fill="#2C6E63" fontFamily="-apple-system, BlinkMacSystemFont, 'PingFang SC', sans-serif" fontSize={9.5} fontWeight={600} letterSpacing={0.2} x={120} y={19}>AI伴学</text>
              <text fill="#7A8B88" fontFamily="-apple-system, BlinkMacSystemFont, 'PingFang SC', sans-serif" fontSize={8} fontWeight={400} letterSpacing={0.3} x={42} y={37}>学有所径，伴有所成</text>
            </svg>
          </a>
          <div className="h-4 w-px bg-outline-variant mx-space-xs hidden lg:block" />
        </div>
        <nav className="flex items-center gap-space-xs">
          {NAV.map((item) => {
            const active = activeKey === item.key;
            return (
              <a
                key={item.key}
                aria-current={active ? 'page' : undefined}
                className={
                  active
                    ? 'px-space-md py-space-xs transition-colors bg-primary-container text-on-primary font-title-md text-title-md rounded-lg shadow-sm'
                    : 'px-space-md py-space-xs font-title-md text-title-md text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface rounded-lg transition-colors'
                }
                data-path={item.key}
                href={`#${item.path}`}
              >
                {item.label}
              </a>
            );
          })}
        </nav>
        <div className="flex items-center gap-space-md shrink-0">
          <div
            className="hidden xl:flex items-center gap-2 px-3 py-1 rounded-full bg-surface-container border border-outline-variant/60"
            title={runtime ? `课程 ${runtime.curriculum.course_id} · RAG ${runtime.rag.segment_count} 条 · ${runtime.rag.index_version}` : runtimeLabel}
          >
            <span className={`w-2 h-2 rounded-full ${backendOffline ? 'bg-error' : runtime?.status === 'degraded' ? 'bg-tertiary' : 'bg-primary'} ${runtime ? '' : 'animate-pulse'}`} />
            <span className="font-label-sm text-label-sm text-on-surface-variant">{runtimeLabel}</span>
          </div>
          <div className="flex items-center gap-2.5 pl-2">
            <div className="w-8 h-8 rounded-full bg-primary-fixed flex items-center justify-center text-primary font-title-md text-sm font-semibold border border-primary/20 shadow-xs">
              {(student?.display_name ?? '李').slice(0, 1)}
            </div>
            <div className="hidden sm:flex flex-col">
              <span className="font-label-sm text-label-sm font-medium text-on-surface">{student?.display_name ?? '演示学生'}</span>
              <span className="text-[11px] text-outline leading-tight">初三强化班</span>
            </div>
          </div>
        </div>
      </div>
    </header>
  );
}
